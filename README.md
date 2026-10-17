# OSRS GP Activity Finder

A local tool that ranks Old School RuneScape money-making methods (processing items,
high alching, GE trading) by GP/hour using live Grand Exchange prices from the OSRS Wiki.

See [docs/PROJECT_SPEC.md](docs/PROJECT_SPEC.md) for the full specification.

## Status

**M2: profit engine.** Prices, hourly volume history and recipes are pulled into a local
SQLite database (`data/osrs.db`) and ranked by GP/hr from the command line. The web UI (M3)
comes next.

## Usage

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                                    # create .venv and install dependencies
uv run python -m backend ingest all        # items, latest prices, current hour, recipes
uv run python -m backend backfill          # one-off: fetch the last 7 days of hourly snapshots (~3 min)
uv run python -m backend report --unmatched 20
uv run python -m backend rank              # top 25 by effective GP/hr
```

`rank` options: `--mode instant|patient|average`, `--sort gp_hr|risk_adjusted`,
`--type recipe|alch`, `--f2p`, `--max-risk low|medium|high`, `--include-illiquid`,
`--search TEXT`, `--top N`.

Individual jobs: `ingest mapping | latest | hourly | recipes`.
Suggested cadence: `latest` every minute, `hourly` every hour, `mapping` daily,
`recipes` weekly. A built-in scheduler arrives with the web server in M3.

Recipe corrections (missing ticks, name aliases, exclusions) go in
[`backend/overrides.toml`](backend/overrides.toml).

## Tests

```bash
uv run pytest
```
