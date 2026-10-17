"""GE item sets and their components, parsed from each set's wiki page.

A set page lists its pieces under ==Components== as {{CostLine|Item name|quantity}} lines.
The wiki has no structured bucket for this, so the page wikitext is read in batches.
"""

import re
import sqlite3
from collections.abc import Callable

from backend import config, db, http

BATCH = 50  # titles per MediaWiki query
_COMPONENTS = re.compile(r"==\s*Components\s*==(.*?)(?:\n==[^=]|\Z)", re.S | re.I)
_COST_LINE = re.compile(r"\{\{\s*CostLine\s*\|([^}|]+)(?:\|([^}|]*))?")


def candidates(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, name FROM items WHERE name LIKE '% set' OR name LIKE '% set (%' ORDER BY name"
    ).fetchall()


def parse_components(wikitext: str) -> list[tuple[str, int]]:
    section = _COMPONENTS.search(wikitext)
    if not section:
        return []
    parts = []
    for name, qty in _COST_LINE.findall(section.group(1)):
        qty = qty.strip()
        parts.append((name.strip(), int(qty) if qty.isdigit() else 1))
    return parts


def fetch_wikitext(titles: list[str], fetch: Callable = http.get_json) -> dict[str, str]:
    """Page title -> wikitext, following redirects."""
    payload = fetch(config.WIKI_API, {
        "action": "query", "prop": "revisions", "rvprop": "content", "rvslots": "main",
        "format": "json", "formatversion": "2", "redirects": "1", "titles": "|".join(titles),
    })
    query = payload.get("query", {})
    renamed = {r["to"]: r["from"] for r in query.get("redirects", [])}
    renamed.update({n["to"]: n["from"] for n in query.get("normalized", [])})
    pages = {}
    for page in query.get("pages", []):
        revisions = page.get("revisions")
        if revisions:
            title = renamed.get(page["title"], page["title"])
            pages[title] = revisions[0]["slots"]["main"]["content"]
    return pages


def refresh(conn: sqlite3.Connection, fetch: Callable = http.get_json) -> dict:
    sets = candidates(conn)
    items = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM items")}
    rows, parsed = [], 0
    for start in range(0, len(sets), BATCH):
        batch = sets[start:start + BATCH]
        pages = fetch_wikitext([s["name"] for s in batch], fetch)
        for s in batch:
            parts = parse_components(pages.get(s["name"], ""))
            if not parts:
                continue
            parsed += 1
            rows.extend((s["id"], i, name, items.get(name), qty) for i, (name, qty) in enumerate(parts))
    with conn:
        conn.execute("DELETE FROM item_sets")
        conn.executemany(
            "INSERT INTO item_sets (set_id, position, name, item_id, quantity) VALUES (?, ?, ?, ?, ?)", rows
        )
        db.mark_refreshed(conn, "sets")
    return {"candidates": len(sets), "sets": parsed, "components": len(rows)}
