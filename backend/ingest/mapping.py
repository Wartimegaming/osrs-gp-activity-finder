"""GE item catalogue: ids, names, buy limits and alch values from /mapping."""

import sqlite3
from collections.abc import Callable

from backend import config, db, http


def refresh(conn: sqlite3.Connection, fetch: Callable = http.get_json) -> int:
    rows = fetch(f"{config.PRICES_API}/mapping")
    with conn:
        conn.executemany(
            """
            INSERT INTO items (id, name, members, buy_limit, value, highalch, lowalch, examine, icon)
            VALUES (:id, :name, :members, :limit, :value, :highalch, :lowalch, :examine, :icon)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name, members = excluded.members, buy_limit = excluded.buy_limit,
                value = excluded.value, highalch = excluded.highalch, lowalch = excluded.lowalch,
                examine = excluded.examine, icon = excluded.icon
            """,
            [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "members": int(bool(r.get("members"))),
                    "limit": r.get("limit"),
                    "value": r.get("value"),
                    "highalch": r.get("highalch"),
                    "lowalch": r.get("lowalch"),
                    "examine": r.get("examine"),
                    "icon": r.get("icon"),
                }
                for r in rows
            ],
        )
        db.mark_refreshed(conn, "mapping")
    return len(rows)
