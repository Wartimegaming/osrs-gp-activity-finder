# OSRS GP Activity Finder

A local tool that ranks Old School RuneScape money-making methods (processing items,
high alching, GE trading) by GP/hour using live Grand Exchange prices from the OSRS Wiki.

See [docs/PROJECT_SPEC.md](docs/PROJECT_SPEC.md) for the full specification.

## Status

**M4: detail view.** A local web app ranks money makers by live GE prices, with filters, an F2P
tag, price modes, auto-refresh and a hiscores level filter. Clicking a method opens its profit
breakdown, what limits its rate, 7-day price and volume charts, and the assumptions behind it.
Data lives in a local SQLite database (`data/osrs.db`) that the server keeps fresh.
Phase 2 adds GE flipping (opt-in from the type filter), potion decanting, item set
exchanges, and favourites and hidden methods. Next: Phase 3 (multi-step chains, shop
arbitrage).

## Quick start

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/) and Node.js 20+.

```bash
uv sync
(cd frontend && npm install && npm run build)
uv run python -m backend serve             # http://localhost:8000
```

On first start the server loads items, recipes and prices in a few seconds, then backfills a
week of hourly price history in the background (~3 minutes). After that it keeps itself
up to date: prices every minute, hourly snapshots every 15 minutes, items daily, recipes weekly.

### Frontend development

```bash
uv run python -m backend serve             # API on :8000
(cd frontend && npm run dev)               # UI with hot reload on http://localhost:5173
```

## Command line

The same data and rankings are available without the UI.

```bash
uv sync                                    # create .venv and install dependencies
uv run python -m backend ingest all        # items, latest prices, current hour, recipes
uv run python -m backend backfill          # one-off: fetch the last 7 days of hourly snapshots (~3 min)
uv run python -m backend report --unmatched 20
uv run python -m backend rank              # top 25 by effective GP/hr
```

`rank` options: `--mode instant|patient|average`, `--sort gp_hr|risk_adjusted`,
`--type recipe|alch|decant|set|flip` (flips only when asked for), `--f2p`, `--max-risk low|medium|high`, `--include-illiquid`,
`--search TEXT`, `--top N`.

Individual jobs: `ingest mapping | latest | hourly | recipes | sets`.
Set `OSRS_DB_PATH` to use a different database file.

Recipe corrections (missing ticks, name aliases, exclusions) go in
[`backend/overrides.toml`](backend/overrides.toml).

## Tests

```bash
uv run pytest
```
