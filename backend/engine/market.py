"""Market snapshot: everything the model needs to know about each GE item.

Loaded once per ranking from SQLite, so the model itself stays pure and testable.
"""

import math
import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class ItemMarket:
    id: int
    name: str
    members: bool
    buy_limit: int | None
    highalch: int | None
    icon: str | None = None
    high: int | None = None  # latest instant-buy price
    high_time: int | None = None
    low: int | None = None  # latest instant-sell price
    low_time: int | None = None
    hour_avg_high: int | None = None  # newest hourly snapshot
    hour_avg_low: int | None = None
    day_avg_high: float | None = None  # volume-weighted over the last 24 snapshots
    day_avg_low: float | None = None
    daily_volume: int = 0
    daily_buy_volume: int | None = None  # of which instant buys (at the high price)
    volatility: float | None = None  # std-dev / mean of hourly mid price over 7 days


@dataclass(frozen=True)
class Market:
    items: dict[int, ItemMarket]
    now: int  # unix time the snapshot represents

    def get(self, item_id: int | None) -> ItemMarket | None:
        return self.items.get(item_id) if item_id is not None else None


def load(conn: sqlite3.Connection, now: int) -> Market:
    newest = conn.execute("SELECT MAX(ts) FROM hourly_prices").fetchone()[0] or 0
    rows = conn.execute(
        """
        WITH day AS (
            SELECT item_id,
                   SUM(high_volume + low_volume) AS volume,
                   SUM(high_volume) AS buy_volume,
                   SUM(avg_high * high_volume) * 1.0 / NULLIF(SUM(CASE WHEN avg_high IS NOT NULL THEN high_volume END), 0) AS avg_high,
                   SUM(avg_low * low_volume) * 1.0 / NULLIF(SUM(CASE WHEN avg_low IS NOT NULL THEN low_volume END), 0) AS avg_low
            FROM hourly_prices WHERE ts > :newest - 86400 GROUP BY item_id
        ),
        mids AS (
            SELECT item_id, (COALESCE(avg_high, avg_low) + COALESCE(avg_low, avg_high)) / 2.0 AS mid
            FROM hourly_prices
            WHERE ts > :newest - 7 * 86400 AND (avg_high IS NOT NULL OR avg_low IS NOT NULL)
        ),
        week AS (
            SELECT item_id, AVG(mid) AS mean, AVG(mid * mid) AS mean_sq, COUNT(*) AS n
            FROM mids GROUP BY item_id
        ),
        hour AS (
            SELECT item_id, avg_high, avg_low FROM hourly_prices WHERE ts = :newest
        )
        SELECT i.id, i.name, i.members, i.buy_limit, i.highalch, i.icon,
               p.high, p.high_time, p.low, p.low_time,
               hour.avg_high AS hour_avg_high, hour.avg_low AS hour_avg_low,
               day.avg_high AS day_avg_high, day.avg_low AS day_avg_low,
               COALESCE(day.volume, 0) AS daily_volume, day.buy_volume AS daily_buy_volume,
               week.mean, week.mean_sq, week.n
        FROM items i
        LEFT JOIN latest_prices p ON p.item_id = i.id
        LEFT JOIN hour ON hour.item_id = i.id
        LEFT JOIN day ON day.item_id = i.id
        LEFT JOIN week ON week.item_id = i.id
        """,
        {"newest": newest},
    ).fetchall()

    items = {}
    for r in rows:
        volatility = None
        if r["n"] and r["n"] >= 24 and r["mean"]:
            variance = max(0.0, r["mean_sq"] - r["mean"] ** 2)
            volatility = math.sqrt(variance) / r["mean"]
        items[r["id"]] = ItemMarket(
            id=r["id"], name=r["name"], members=bool(r["members"]),
            buy_limit=r["buy_limit"], highalch=r["highalch"], icon=r["icon"],
            high=r["high"], high_time=r["high_time"], low=r["low"], low_time=r["low_time"],
            hour_avg_high=r["hour_avg_high"], hour_avg_low=r["hour_avg_low"],
            day_avg_high=r["day_avg_high"], day_avg_low=r["day_avg_low"],
            daily_volume=r["daily_volume"], daily_buy_volume=r["daily_buy_volume"], volatility=volatility,
        )
    return Market(items=items, now=now)
