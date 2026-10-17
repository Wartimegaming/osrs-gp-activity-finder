"""Command-line entry point: `python3 -m backend <command>`."""

import argparse
import time

from backend import db
from backend.engine.model import Risk
from backend.engine.ranking import Filters, SortKey, evaluate_all, rank
from backend.engine.settings import PriceMode, Settings
from backend.ingest import icons, mapping, prices, recipes, sets, shops


def cmd_ingest(conn, args) -> None:
    jobs = ["mapping", "latest", "hourly", "recipes", "sets", "shops"] if args.job == "all" else [args.job]
    for job in jobs:
        started = time.monotonic()
        if job == "mapping":
            result = f"{mapping.refresh(conn)} items"
        elif job == "latest":
            result = f"{prices.refresh_latest(conn)} prices"
        elif job == "hourly":
            result = f"{prices.refresh_hourly(conn)} item rows"
        elif job == "icons":
            stats = icons.download(conn)
            result = f"{stats['saved']} icons saved, {stats['failed']} failed, {stats['remaining']} still missing"
        elif job == "shops":
            stats = shops.refresh(conn)
            result = f"{stats['resellable']} resellable shop items from {stats['shops']} shops"
        elif job == "sets":
            stats = sets.refresh(conn)
            result = f"{stats['sets']} sets with {stats['components']} pieces"
        else:
            stats = recipes.refresh(conn)
            result = (
                f"{stats['bucket_rows']} bucket rows, {stats['item_recipes']} item recipes, "
                f"{stats['ge_viable']} GE-viable"
            )
        print(f"{job:<8} {result} ({time.monotonic() - started:.1f}s)")


def cmd_backfill(conn, args) -> None:
    fetched = prices.backfill(conn, args.hours)
    print(f"backfilled {fetched} hourly snapshots; "
          f"{prices.snapshot_coverage(conn, 24)}/24 hours of daily volume available")


def cmd_report(conn, args) -> None:
    one = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
    print("Data")
    print(f"  items               {one('SELECT COUNT(*) FROM items')}")
    print(f"  latest prices       {one('SELECT COUNT(*) FROM latest_prices')}")
    print(f"  hourly snapshots    {one('SELECT COUNT(DISTINCT ts) FROM hourly_prices')} hours "
          f"({prices.snapshot_coverage(conn, 24)}/24 in the last day, "
          f"{prices.snapshot_coverage(conn, 168)}/168 in the last week)")
    print(f"  items with volume   {one('SELECT COUNT(*) FROM daily_volume')}")
    print("Recipes")
    print(f"  item recipes        {one('SELECT COUNT(*) FROM recipes')}")
    print(f"  GE-viable           {one('SELECT COUNT(*) FROM recipes WHERE ge_viable')}")
    print(f"    with known ticks  {one('SELECT COUNT(*) FROM recipes WHERE ge_viable AND ticks IS NOT NULL')}")
    print(f"    zero-tick         {one("SELECT COUNT(*) FROM recipes WHERE ge_viable AND ticks_source = 'zero'")}")
    print(f"    F2P               {one('SELECT COUNT(*) FROM recipes WHERE f2p')}")
    print(f"    excluded          {one('SELECT COUNT(*) FROM recipes WHERE excluded')}")
    print("Last refreshed")
    for row in conn.execute("SELECT key, value FROM meta WHERE key LIKE 'refreshed:%' ORDER BY key"):
        age = int(time.time()) - int(row["value"])
        print(f"  {row['key'].split(':', 1)[1]:<8} {age // 60} min ago")
    if args.unmatched:
        print(f"Names not on the GE (top {args.unmatched})")
        for row in recipes.unmatched_names(conn, args.unmatched):
            print(f"  {row['uses']:>4}  {row['name']}")


def _gp(value: float | None) -> str:
    if value is None:
        return "-"
    for limit, suffix in ((1e9, "b"), (1e6, "m"), (1e3, "k")):
        if abs(value) >= limit:
            return f"{value / limit:.1f}{suffix}"
    return f"{value:.0f}"


def cmd_rank(conn, args) -> None:
    settings = Settings(price_mode=PriceMode(args.mode), sell_window_hours=args.sell_hours)
    filters = Filters(
        # Flipping is passive GE-offer time, not comparable with active methods: opt in with --type flip.
        types=frozenset(args.type or ("recipe", "alch", "decant", "set", "shop", "chain")),
        f2p_only=args.f2p,
        include_illiquid=args.include_illiquid,
        max_risk=Risk(args.max_risk) if args.max_risk else None,
        search=args.search or "",
        min_consistency=args.min_consistency,
        min_daily_volume=args.min_volume,
    )
    results = rank(evaluate_all(conn, settings), filters, SortKey(args.sort))
    header = (f"{'#':>3}  {'Activity':<34} {'Type':<6} {'Skill':<14} {'GP/hr':>7} {'Risk-adj':>8} "
              f"{'Profit':>7} {'Act/hr':>6} {'Limit':<9} {'Day vol':>7} {'ROI':>6} {'7d':>4} {'Risk':<6} Flags")
    print(header)
    print("-" * len(header))
    for i, r in enumerate(results[: args.top], 1):
        name = r.spec.name + (f" ({r.spec.variant})" if r.spec.variant else "")
        skill = ", ".join(f"{s} {lvl}" for s, lvl in r.spec.skills if lvl) or "-"
        volume = (r.outputs or r.inputs)[0].daily_volume
        print(f"{i:>3}  {name[:34]:<34} {r.spec.type:<6} {skill[:14]:<14} {_gp(r.gp_hr):>7} "
              f"{_gp(r.gp_hr_risk_adjusted):>8} {_gp(r.profit):>7} {r.effective_actions:>6.0f} "
              f"{r.limiting_factor:<9} {_gp(volume):>7} {r.roi * 100 if r.roi is not None else 0:>5.1f}% "
              f"{f'{r.consistency * 100:.0f}%' if r.consistency is not None else '-':>4} "
              f"{r.risk:<6} {','.join(sorted(r.flags)) or '-'}")
    print(f"\n{len(results)} profitable activities ({args.mode} prices). "
          f"Use --include-illiquid to show those that fail the volume filter.")


def cmd_serve(conn, args) -> None:
    import logging

    import uvicorn

    from backend.api.app import create_app

    conn.close()  # the server manages its own connections
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    uvicorn.run(create_app(run_scheduler=not args.no_refresh), host=args.host, port=args.port)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python3 -m backend")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="refresh data from the wiki")
    ingest.add_argument("job", choices=["all", "mapping", "latest", "hourly", "recipes", "sets", "shops", "icons"])
    ingest.set_defaults(func=cmd_ingest)

    backfill = sub.add_parser("backfill", help="fetch missing historical hourly snapshots")
    backfill.add_argument("--hours", type=int, default=168)
    backfill.set_defaults(func=cmd_backfill)

    report = sub.add_parser("report", help="summarise what's in the database")
    report.add_argument("--unmatched", type=int, default=0, metavar="N",
                        help="also list the N most used recipe names that aren't GE items")
    report.set_defaults(func=cmd_report)

    ranking = sub.add_parser("rank", help="rank activities by GP/hr")
    ranking.add_argument("--top", type=int, default=25)
    ranking.add_argument("--mode", choices=[m.value for m in PriceMode], default="instant")
    ranking.add_argument("--sort", choices=[k.value for k in SortKey], default="gp_hr")
    ranking.add_argument("--sell-hours", type=int, choices=[1, 4, 12, 24], default=1,
                         help="hours you'll take to sell an hour's output (steady-priced methods only)")
    ranking.add_argument("--type", action="append", choices=["recipe", "alch", "flip", "decant", "set", "shop", "chain"])
    ranking.add_argument("--min-volume", type=int, metavar="UNITS",
                         help="only methods whose product trades at least this many a day")
    ranking.add_argument("--min-consistency", type=float, metavar="SHARE",
                         help="only methods profitable in at least this share of last week's hours, e.g. 0.8")
    ranking.add_argument("--f2p", action="store_true", help="free-to-play methods only")
    ranking.add_argument("--max-risk", choices=[r.value for r in Risk])
    ranking.add_argument("--include-illiquid", action="store_true")
    ranking.add_argument("--search")
    ranking.set_defaults(func=cmd_rank)

    serve = sub.add_parser("serve", help="run the web UI and API with background refresh")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--no-refresh", action="store_true", help="don't run background refresh jobs")
    serve.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    conn = db.connect()
    try:
        args.func(conn, args)
    finally:
        conn.close()
