"""Live prices (/latest) and hourly snapshots (/1h), including historical backfill.

Daily volume is computed from our own hourly snapshots (see the daily_volume view)
because the wiki's /24h endpoint is served from a long-lived cache and can be days old.
"""

import sqlite3
import time
from collections.abc import Callable

from backend import config, db, http


def refresh_latest(conn: sqlite3.Connection, fetch: Callable = http.get_json) -> int:
    data = fetch(f"{config.PRICES_API}/latest")["data"]
    known = _known_item_ids(conn)
    rows = [
        (int(item_id), p.get("high"), p.get("highTime"), p.get("low"), p.get("lowTime"))
        for item_id, p in data.items()
        if int(item_id) in known
    ]
    with conn:
        conn.executemany(
            """
            INSERT INTO latest_prices (item_id, high, high_time, low, low_time)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(item_id) DO UPDATE SET
                high = excluded.high, high_time = excluded.high_time,
                low = excluded.low, low_time = excluded.low_time
            """,
            rows,
        )
        db.mark_refreshed(conn, "latest")
    return len(rows)


def store_hour(conn: sqlite3.Connection, payload: dict) -> int:
    """Store one /1h response. Returns the number of item rows written."""
    ts = payload["timestamp"]
    known = _known_item_ids(conn)
    rows = [
        (
            int(item_id),
            ts,
            p.get("avgHighPrice"),
            p.get("highPriceVolume") or 0,
            p.get("avgLowPrice"),
            p.get("lowPriceVolume") or 0,
        )
        for item_id, p in payload["data"].items()
        if int(item_id) in known
    ]
    with conn:
        conn.executemany(
            "INSERT OR REPLACE INTO hourly_prices "
            "(item_id, ts, avg_high, high_volume, avg_low, low_volume) VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
    return len(rows)


def refresh_hourly(conn: sqlite3.Connection, fetch: Callable = http.get_json) -> int:
    count = store_hour(conn, fetch(f"{config.PRICES_API}/1h"))
    with conn:
        prune(conn)
        db.mark_refreshed(conn, "hourly")
    return count


def backfill(
    conn: sqlite3.Connection,
    hours: int,
    fetch: Callable = http.get_json,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Fetch any of the last `hours` hourly snapshots we don't already have."""
    latest = fetch(f"{config.PRICES_API}/1h")
    store_hour(conn, latest)
    newest = latest["timestamp"]
    have = {r["ts"] for r in conn.execute("SELECT DISTINCT ts FROM hourly_prices")}
    fetched = 0
    for i in range(1, hours):
        ts = newest - i * 3600
        if ts in have:
            continue
        sleep(config.BACKFILL_DELAY_SECONDS)
        store_hour(conn, fetch(f"{config.PRICES_API}/1h", {"timestamp": ts}))
        fetched += 1
    with conn:
        prune(conn)
        db.mark_refreshed(conn, "hourly")
    return fetched


def prune(conn: sqlite3.Connection) -> None:
    cutoff = int(time.time()) - config.SNAPSHOT_RETENTION_DAYS * 86400
    conn.execute("DELETE FROM hourly_prices WHERE ts < ?", (cutoff,))


def snapshot_coverage(conn: sqlite3.Connection, hours: int = 24) -> int:
    """How many of the last `hours` hourly snapshots are stored."""
    row = conn.execute(
        "SELECT COUNT(DISTINCT ts) AS n FROM hourly_prices "
        "WHERE ts > (SELECT MAX(ts) FROM hourly_prices) - ?",
        (hours * 3600,),
    ).fetchone()
    return row["n"]


def _known_item_ids(conn: sqlite3.Connection) -> set[int]:
    return {r["id"] for r in conn.execute("SELECT id FROM items")}
