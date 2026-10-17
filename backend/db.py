"""SQLite schema and connection helpers."""

import sqlite3
import time
from pathlib import Path

from backend import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    members     INTEGER NOT NULL,
    buy_limit   INTEGER,            -- GE buy limit per 4 hours; NULL when unknown
    value       INTEGER,
    highalch    INTEGER,
    lowalch     INTEGER,
    examine     TEXT,
    icon        TEXT
);

CREATE TABLE IF NOT EXISTS latest_prices (
    item_id     INTEGER PRIMARY KEY REFERENCES items(id),
    high        INTEGER,            -- last instant-buy price
    high_time   INTEGER,
    low         INTEGER,            -- last instant-sell price
    low_time    INTEGER
);

-- One row per item per hour, from /1h. Daily volume and volatility are computed from these.
CREATE TABLE IF NOT EXISTS hourly_prices (
    item_id     INTEGER NOT NULL,
    ts          INTEGER NOT NULL,   -- start of the hour (API timestamp)
    avg_high    INTEGER,
    high_volume INTEGER NOT NULL,
    avg_low     INTEGER,
    low_volume  INTEGER NOT NULL,
    PRIMARY KEY (item_id, ts)
);

CREATE TABLE IF NOT EXISTS recipes (
    recipe_key   TEXT PRIMARY KEY,  -- page_name_sub + content hash; stable across refreshes
    page_name    TEXT NOT NULL,
    page_name_sub TEXT NOT NULL,
    variant      TEXT,              -- output subtext, e.g. "Blast furnace"
    output_name  TEXT NOT NULL,
    output_item_id INTEGER,         -- NULL when the output is not on the GE
    output_qty   REAL NOT NULL,
    ticks        INTEGER,           -- game ticks per action; NULL when unknown
    ticks_source TEXT NOT NULL,     -- wiki | zero | unknown | override
    ticks_raw    TEXT,
    efficiency   REAL,              -- per-recipe override; NULL means use the default
    actions_per_hour REAL,          -- per-recipe override; skips the tick model
    members      INTEGER NOT NULL,
    f2p          INTEGER NOT NULL,  -- recipe and every item involved are free-to-play
    ge_viable    INTEGER NOT NULL,  -- output and every material can be traded on the GE
    excluded     INTEGER NOT NULL DEFAULT 0,
    tools        TEXT,
    facilities   TEXT,
    note         TEXT
);

CREATE TABLE IF NOT EXISTS recipe_materials (
    recipe_key  TEXT NOT NULL REFERENCES recipes(recipe_key) ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    name        TEXT NOT NULL,
    item_id     INTEGER,            -- NULL for coins and items not on the GE
    kind        TEXT NOT NULL,      -- item | coins | untradeable
    quantity    REAL NOT NULL,
    PRIMARY KEY (recipe_key, position)
);

CREATE TABLE IF NOT EXISTS recipe_skills (
    recipe_key  TEXT NOT NULL REFERENCES recipes(recipe_key) ON DELETE CASCADE,
    skill       TEXT NOT NULL,
    level       INTEGER,
    experience  REAL,
    boostable   INTEGER NOT NULL,
    PRIMARY KEY (recipe_key, skill)
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Trade volume over the 24 hours ending at the newest snapshot.
CREATE VIEW IF NOT EXISTS daily_volume AS
SELECT item_id,
       SUM(high_volume + low_volume) AS volume,
       SUM(high_volume)              AS high_volume,
       SUM(low_volume)               AS low_volume
FROM hourly_prices
WHERE ts > (SELECT MAX(ts) FROM hourly_prices) - 86400
GROUP BY item_id;

CREATE INDEX IF NOT EXISTS idx_hourly_ts ON hourly_prices(ts);
CREATE INDEX IF NOT EXISTS idx_materials_item ON recipe_materials(item_id);
CREATE INDEX IF NOT EXISTS idx_recipes_output ON recipes(output_item_id);
"""


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    path = config.DB_PATH if path is None else path
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")  # the server's refresh jobs write concurrently
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


# Columns added after a table was first created: (table, column, definition).
_ADDED_COLUMNS = [
    ("recipes", "actions_per_hour", "REAL"),
]


def _migrate(conn: sqlite3.Connection) -> None:
    for table, column, definition in _ADDED_COLUMNS:
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def set_meta(conn: sqlite3.Connection, key: str, value: str | int | float) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def mark_refreshed(conn: sqlite3.Connection, job: str) -> None:
    set_meta(conn, f"refreshed:{job}", int(time.time()))
