"""NPC shop stock from the wiki `storeline` and `infobox_shop` buckets.

Only shops that sell for coins and items that trade on the GE are kept, since those are
the only ones that can be resold.
"""

import re
import sqlite3
from collections.abc import Callable

from backend import config, db, http
from backend.ingest.sets import BATCH, fetch_wikitext

# The bucket's is_members_only field is empty for every shop, so read the infobox instead.
_MEMBERS = re.compile(r"\|\s*members\s*=\s*(yes|no)\b", re.I)


def shop_members(names: list[str], fetch: Callable) -> dict[str, bool]:
    """Shop page -> members-only, from each page's infobox. Missing pages are left out."""
    members = {}
    for start in range(0, len(names), BATCH):
        for title, text in fetch_wikitext(names[start:start + BATCH], fetch).items():
            match = _MEMBERS.search(text)
            if match:
                members[title] = match.group(1).lower() == "yes"
    return members


def _bucket(fetch: Callable, name: str, fields: list[str]) -> list[dict]:
    rows, offset = [], 0
    select = ",".join(f"'{f}'" for f in fields)
    while True:
        query = f"bucket('{name}').select({select}).limit({config.BUCKET_PAGE_SIZE}).offset({offset}).run()"
        payload = fetch(config.WIKI_API, {"action": "bucket", "format": "json", "query": query})
        if "error" in payload:
            raise RuntimeError(f"Wiki bucket query failed: {payload['error']}")
        page = payload.get("bucket", [])
        rows.extend(page)
        if len(page) < config.BUCKET_PAGE_SIZE:
            return rows
        offset += config.BUCKET_PAGE_SIZE


def _int(value) -> int | None:
    text = str(value or "").replace(",", "").strip()
    return int(text) if text.lstrip("-").isdigit() else None


def _clean_link(text: str | None) -> str | None:
    """'[[Lumbridge]]' -> 'Lumbridge', '[[A|B]]' -> 'B'."""
    if not text:
        return None
    out = text
    while "[[" in out and "]]" in out:
        start, end = out.index("[["), out.index("]]")
        inner = out[start + 2:end].split("|")[-1]
        out = out[:start] + inner + out[end + 2:]
    return out.strip() or None


def refresh(conn: sqlite3.Connection, fetch: Callable = http.get_json) -> dict:
    lines = _bucket(fetch, "storeline", [
        "sold_by", "sold_item", "store_sell_price", "store_currency", "store_delta",
        "store_stock", "store_sell_multiplier", "restock_time", "store_notes",
    ])
    shops = {s["page_name"]: s for s in _bucket(fetch, "infobox_shop", ["page_name", "location"])}
    items = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM items")}
    sellers = sorted({
        line["sold_by"] for line in lines
        if line.get("store_currency") == "Coins" and line.get("sold_item") in items
    })
    members = shop_members(sellers, fetch)

    rows = []
    for line in lines:
        price = _int(line.get("store_sell_price"))
        item_id = items.get(line.get("sold_item"))
        if line.get("store_currency") != "Coins" or price is None or price <= 0 or item_id is None:
            continue
        shop = shops.get(line.get("sold_by"), {})
        stock = str(line.get("store_stock", "")).strip()
        rows.append((
            line["sold_by"], item_id, line["sold_item"], price,
            None if stock == "∞" else _int(stock),  # NULL = unlimited
            _int(line.get("store_delta")) or 0,
            _int(line.get("store_sell_multiplier")),
            _int(line.get("restock_time")),
            line.get("store_notes") or None,
            1 if members.get(line["sold_by"], True) else 0,  # unknown shops count as members
            _clean_link(shop.get("location")),
        ))
    with conn:
        conn.execute("DELETE FROM shop_items")
        conn.executemany(
            "INSERT OR IGNORE INTO shop_items (shop, item_id, item_name, price, stock, delta, sell_multiplier, "
            "restock_ticks, notes, members, location) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        db.mark_refreshed(conn, "shops")
    return {"store_lines": len(lines), "shops": len(shops), "resellable": len(rows)}
