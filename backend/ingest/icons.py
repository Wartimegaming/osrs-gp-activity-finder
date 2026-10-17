"""Local copies of item icons.

Each distinct icon file is downloaded from the wiki once, slowly, into assets/icons/ and then
served by this app. Files that already exist are never fetched again.
"""

import logging
import re
import sqlite3
import time
import urllib.error
import urllib.parse
from collections.abc import Callable
from pathlib import Path

from backend import config, db, http

log = logging.getLogger("icons")
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_UNSAFE = re.compile(r"[^A-Za-z0-9 _.'()+,&!-]")


def filename(icon: str) -> str:
    """Wiki icon name -> safe local filename ('Ahrim's hood.png' stays readable)."""
    name = _UNSAFE.sub("_", icon.replace("/", "_").replace("\\", "_")).strip(" .")
    return name if name.lower().endswith(".png") else f"{name}.png"


def path_for(icon: str, directory: Path | None = None) -> Path:
    return (directory or config.ICONS_DIR) / filename(icon)


def missing(conn: sqlite3.Connection, directory: Path | None = None) -> list[str]:
    icons = [r["icon"] for r in conn.execute("SELECT DISTINCT icon FROM items WHERE icon IS NOT NULL ORDER BY icon")]
    return [icon for icon in icons if not path_for(icon, directory).exists()]


def download(
    conn: sqlite3.Connection,
    limit: int | None = None,
    fetch: Callable[[str], bytes] = http.get_bytes,
    sleep: Callable[[float], None] = time.sleep,
    directory: Path | None = None,
) -> dict:
    directory = directory or config.ICONS_DIR
    directory.mkdir(parents=True, exist_ok=True)
    todo = missing(conn, directory)[:limit]
    saved = failed = 0
    for i, icon in enumerate(todo):
        if i:
            sleep(config.ICON_DELAY_SECONDS)
        url = f"{config.WIKI_IMAGES}/{urllib.parse.quote(icon.replace(' ', '_'))}"
        try:
            body = fetch(url)
        except urllib.error.HTTPError as exc:
            log.warning("icon %s: HTTP %s", icon, exc.code)
            failed += 1
            continue
        if not body.startswith(PNG_MAGIC):
            log.warning("icon %s: not a PNG", icon)
            failed += 1
            continue
        target = path_for(icon, directory)
        tmp = target.with_suffix(".part")
        tmp.write_bytes(body)
        tmp.replace(target)  # never leave a half-written icon behind
        saved += 1
    with conn:
        db.mark_refreshed(conn, "icons")
    return {"saved": saved, "failed": failed, "remaining": len(missing(conn, directory))}
