"""Minimal JSON-over-HTTP client with the wiki User-Agent and retries."""

import json
import time
import urllib.error
import urllib.parse
import urllib.request

from backend import config


def get_json(url: str, params: dict | None = None) -> dict | list:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT})
    for attempt in range(1, config.HTTP_RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=config.HTTP_TIMEOUT) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == config.HTTP_RETRIES:
                raise
        except urllib.error.URLError:
            if attempt == config.HTTP_RETRIES:
                raise
        time.sleep(2**attempt)
    raise RuntimeError("unreachable")
