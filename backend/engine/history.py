"""'Consistently profitable' score: how often a method was profitable over the last 7 days.

Each activity is re-priced at every stored hourly snapshot, using the hourly averages on the
same side of the book as the current price mode. An hour counts only when every item in the
activity traded in it; at least a day of such hours is needed for a score.
"""

import sqlite3
import statistics
import threading
from dataclasses import dataclass

from backend.engine.model import ActivitySpec, ge_tax
from backend.engine.settings import PriceMode, Settings

WINDOW_HOURS = 168
MIN_HOURS = 24


@dataclass(frozen=True)
class Consistency:
    share: float  # fraction of hours that were profitable
    median_profit: float
    hours: int


Series = dict[int, dict[int, tuple[int | None, int | None]]]  # item -> ts -> (avg_high, avg_low)


def load_series(conn: sqlite3.Connection, hours: int = WINDOW_HOURS) -> tuple[int | None, Series]:
    newest = conn.execute("SELECT MAX(ts) FROM hourly_prices").fetchone()[0]
    series: Series = {}
    if newest is None:
        return None, series
    for item_id, ts, high, low in conn.execute(
        "SELECT item_id, ts, avg_high, avg_low FROM hourly_prices WHERE ts > ?", (newest - hours * 3600,)
    ):
        series.setdefault(item_id, {})[ts] = (high, low)
    return newest, series


def score(spec: ActivitySpec, series: Series, settings: Settings) -> Consistency | None:
    mode = spec.price_mode or settings.price_mode
    buy_high = mode is not PriceMode.PATIENT  # instant/average buy at the high side
    items = [leg for leg in spec.inputs + spec.outputs if leg.kind == "item"]
    if not items or any(leg.item_id not in series for leg in items):
        return None
    hours = set.intersection(*(set(series[leg.item_id]) for leg in items))
    profits = []
    for ts in hours:
        total = spec.fixed_revenue
        for leg in spec.inputs:
            if leg.kind == "coins":
                total -= leg.quantity
                continue
            high, low = series[leg.item_id][ts]
            price = high if buy_high else low
            if price is None:
                break
            total -= price * leg.quantity
        else:
            for leg in spec.outputs:
                high, low = series[leg.item_id][ts]
                price = low if buy_high else high
                if price is None:
                    break
                total += (price - ge_tax(price, settings, leg.item_id)) * leg.quantity
            else:
                profits.append(total)
    if len(profits) < MIN_HOURS:
        return None
    return Consistency(
        share=sum(p > 0 for p in profits) / len(profits),
        median_profit=statistics.median(profits),
        hours=len(profits),
    )


class ConsistencyCache:
    """Scores only change when a new hourly snapshot lands, so keep them between rankings."""

    def __init__(self):
        self._lock = threading.Lock()
        self._newest: int | None = None
        self._series: Series = {}
        self._scores: dict[PriceMode, dict[str, Consistency | None]] = {}

    def scores(self, conn: sqlite3.Connection, specs: list[ActivitySpec], settings: Settings) -> dict[str, Consistency | None]:
        with self._lock:
            newest = conn.execute("SELECT MAX(ts) FROM hourly_prices").fetchone()[0]
            if newest != self._newest or not self._series:
                self._newest, self._series = load_series(conn)
                self._scores = {}
            scores = self._scores.setdefault(settings.price_mode, {})
            for spec in specs:
                if spec.key not in scores:
                    scores[spec.key] = score(spec, self._series, settings)
            return scores


CACHE = ConsistencyCache()
