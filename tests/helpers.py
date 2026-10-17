"""Shared test fixtures: an in-memory database and a fake wiki fetcher."""

import json
from pathlib import Path

from backend import db

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


def memory_db():
    return db.connect(":memory:")


class FakeFetch:
    """Stands in for http.get_json. Routes are matched on the URL suffix."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[tuple[str, dict | None]] = []

    def __call__(self, url: str, params: dict | None = None):
        self.calls.append((url, params))
        for suffix, response in self.routes.items():
            if url.endswith(suffix):
                return response(params) if callable(response) else response
        raise AssertionError(f"unexpected request: {url} {params}")
