"""Minimal HTTP client for the wiki: identifying User-Agent, gzip, and retries."""

import gzip
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from backend import config


def get_bytes(url: str, params: dict | None = None) -> bytes:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    # Asking for gzip cuts the price endpoints to about a fifth of their size.
    request = urllib.request.Request(
        url, headers={"User-Agent": config.USER_AGENT, "Accept-Encoding": "gzip"}
    )
    for attempt in range(1, config.HTTP_RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=config.HTTP_TIMEOUT) as response:
                body = response.read()
                if response.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
                return body
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == config.HTTP_RETRIES:
                raise
        except urllib.error.URLError:
            if attempt == config.HTTP_RETRIES:
                raise
        time.sleep(2**attempt)
    raise RuntimeError("unreachable")


def get_json(url: str, params: dict | None = None) -> dict | list:
    return json.loads(get_bytes(url, params))
