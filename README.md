# OSRS GP Activity Finder

A local tool that ranks Old School RuneScape money-making methods (processing items,
high alching, GE trading) by GP/hour using live Grand Exchange prices from the OSRS Wiki.

See [docs/PROJECT_SPEC.md](docs/PROJECT_SPEC.md) for the full specification.

## Status

**M1: data layer.** Prices, hourly volume history and recipes are pulled into a local
SQLite database (`data/osrs.db`). The profit engine (M2) and web UI (M3) come next.

## Usage

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                                    # create .venv and install dependencies
uv run python -m backend ingest all        # items, latest prices, current hour, recipes
uv run python -m backend backfill          # one-off: fetch the last 7 days of hourly snapshots (~3 min)
uv run python -m backend report --unmatched 20
```

Individual jobs: `ingest mapping | latest | hourly | recipes`.
Suggested cadence: `latest` every minute, `hourly` every hour, `mapping` daily,
`recipes` weekly. A built-in scheduler arrives with the web server in M3.

Recipe corrections (missing ticks, name aliases, exclusions) go in
[`backend/overrides.toml`](backend/overrides.toml).

## Tests

```bash
uv run pytest
```
