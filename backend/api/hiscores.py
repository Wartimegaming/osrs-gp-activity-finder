"""Player skill levels from the official OSRS hiscores, cached briefly in memory."""

import time
import urllib.error
from collections.abc import Callable

from backend import http

HISCORES_URL = "https://secure.runescape.com/m=hiscore_oldschool/index_lite.json"
CACHE_SECONDS = 300


class PlayerNotFound(Exception):
    pass


_cache: dict[str, tuple[float, dict]] = {}


def lookup(name: str, fetch: Callable = http.get_json, now: Callable[[], float] = time.time) -> dict:
    """Returns {"name": ..., "levels": {"crafting": 85, ...}} with lower-case skill names."""
    key = name.strip().lower()
    cached = _cache.get(key)
    if cached and now() - cached[0] < CACHE_SECONDS:
        return cached[1]
    try:
        payload = fetch(HISCORES_URL, {"player": name.strip()})
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise PlayerNotFound(name) from exc
        raise
    levels = {
        s["name"].lower(): max(1, s["level"])  # unranked skills come back as -1
        for s in payload["skills"]
        if s["name"] != "Overall"
    }
    result = {"name": payload.get("name", name), "levels": levels}
    _cache[key] = (now(), result)
    return result
