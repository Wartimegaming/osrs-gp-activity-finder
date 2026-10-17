"""Command-line entry point: `python3 -m backend <command>`."""

import argparse
import time

from backend import db
from backend.ingest import mapping, prices, recipes


def cmd_ingest(conn, args) -> None:
    jobs = ["mapping", "latest", "hourly", "recipes"] if args.job == "all" else [args.job]
    for job in jobs:
        started = time.monotonic()
        if job == "mapping":
            result = f"{mapping.refresh(conn)} items"
        elif job == "latest":
            result = f"{prices.refresh_latest(conn)} prices"
        elif job == "hourly":
            result = f"{prices.refresh_hourly(conn)} item rows"
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


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python3 -m backend")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="refresh data from the wiki")
    ingest.add_argument("job", choices=["all", "mapping", "latest", "hourly", "recipes"])
    ingest.set_defaults(func=cmd_ingest)

    backfill = sub.add_parser("backfill", help="fetch missing historical hourly snapshots")
    backfill.add_argument("--hours", type=int, default=168)
    backfill.set_defaults(func=cmd_backfill)

    report = sub.add_parser("report", help="summarise what's in the database")
    report.add_argument("--unmatched", type=int, default=0, metavar="N",
                        help="also list the N most used recipe names that aren't GE items")
    report.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    conn = db.connect()
    try:
        args.func(conn, args)
    finally:
        conn.close()
