"""Merchanting: margin-flip candidates and their signals."""

import unittest
from dataclasses import replace

from backend.engine import merch
from backend.engine.settings import Settings
from tests.test_engine import NOW, item, market

S = Settings()
HOUR = 3600


def steady_week(item_id, high=110, low=100, hours=168, step=0):
    """Hourly history with a constant spread; `step` moves the price each hour (oldest first)."""
    return {item_id: {NOW - (hours - i) * HOUR: (high + step * i, low + step * i) for i in range(hours)}}


# 24,000 trades a day, half each side = 500/hr per side, so 50/hr is our 10% share.
BASE = item(1, "Thing", high=110, low=100, volume=24_000, limit=1000, daily_buy_volume=12_000)


def analyse(it=BASE, series=None):
    return merch.analyse(it, market(it), series if series is not None else steady_week(it.id), S)


def labels(c):
    return {s.key for s in c.signals}


class CandidateTest(unittest.TestCase):
    def test_margin_and_units(self):
        c = analyse()
        self.assertEqual((c.buy_price, c.sell_price, c.tax, c.margin), (100, 110, 2, 8))
        self.assertAlmostEqual(c.roi, 0.08)
        self.assertEqual((c.sellers_per_hour, c.buyers_per_hour), (500, 500))
        self.assertEqual(c.units_per_window, 200)  # 50/hr × 4h, under the 1,000 limit
        self.assertEqual(c.profit_per_window, 1600)
        self.assertEqual(c.capital, 20_000)

    def test_buy_limit_caps_units(self):
        c = analyse(replace(BASE, buy_limit=80))
        self.assertEqual(c.units_per_window, 80)
        self.assertIn("limit", labels(c))

    def test_slower_side_sets_the_pace(self):
        c = analyse(replace(BASE, daily_buy_volume=2_400))  # 100/hr buy, 900/hr sell
        self.assertEqual(c.units_per_window, 40)
        self.assertIn("one_sided", labels(c))

    def test_no_margin_or_market(self):
        self.assertIsNone(analyse(replace(BASE, high=101)))  # tax eats it
        self.assertIsNone(analyse(replace(BASE, daily_volume=10, daily_buy_volume=5)))

    def test_high_confidence(self):
        c = analyse()
        self.assertEqual(c.confidence, "high")
        self.assertTrue({"wide", "steady", "liquid"} <= labels(c))
        self.assertAlmostEqual(c.margin_steady, 1.0)

    def test_stale_quote(self):
        c = analyse(replace(BASE, low_time=NOW - 2 * HOUR))
        self.assertIn("stale", labels(c))
        self.assertEqual(c.confidence, "low")
        self.assertLess(c.adjusted_profit, analyse().adjusted_profit)

    def test_thin_margin(self):
        # 2% tax on 1,025,400 is 20,508, leaving 4,892: under 0.5% of the buy price.
        pricey = replace(BASE, high=1_025_400, low=1_000_000)
        c = analyse(pricey, steady_week(1, 1_025_400, 1_000_000))
        self.assertIn("thin_margin", labels(c))
        self.assertLess(c.adjusted_profit, c.profit_per_window)

    def test_unusual_margin(self):
        c = analyse(replace(BASE, high=130), steady_week(1, 110, 100))  # 27 now vs 8 typical
        self.assertIn("unusual", labels(c))
        self.assertNotEqual(c.confidence, "high")


class WeekTest(unittest.TestCase):
    def test_near_low_and_falling(self):
        # Price fell 1 gp an hour all week, so today's price is at the bottom of the range.
        series = steady_week(1, high=280, low=270, step=-1)
        c = analyse(replace(BASE, high=112, low=102), series)
        self.assertLess(c.position, 0.05)
        self.assertLess(c.trend_24h, -0.03)
        self.assertTrue({"low", "falling"} <= labels(c))

    def test_near_high_and_rising(self):
        series = steady_week(1, high=110, low=100, step=1)
        c = analyse(replace(BASE, high=279, low=269), series)
        self.assertGreater(c.position, 0.95)
        self.assertTrue({"high", "rising"} <= labels(c))

    def test_flat_week_is_mid_range(self):
        c = analyse()
        self.assertAlmostEqual(c.position, 0.5)
        self.assertFalse({"low", "high"} & labels(c))

    def test_needs_a_day_of_history(self):
        c = analyse(series=steady_week(1, hours=10))
        self.assertIsNone(c.position)
        self.assertIsNone(c.margin_steady)

    def test_unreliable_margin(self):
        series = {1: {NOW - i * HOUR: ((110, 100) if i % 3 == 0 else (100, 100)) for i in range(48)}}
        c = analyse(series=series)
        self.assertAlmostEqual(c.margin_steady, 16 / 48)
        self.assertIn("unreliable", labels(c))


class RankingTest(unittest.TestCase):
    def test_sorted_by_adjusted_profit(self):
        good = BASE
        stale = replace(BASE, id=2, name="Stale", low_time=NOW - 2 * HOUR)
        series = {**steady_week(1), **steady_week(2)}
        ranked = merch.candidates(market(good, stale), series, S)
        self.assertEqual([c.name for c in ranked], ["Thing", "Stale"])


if __name__ == "__main__":
    unittest.main()


class MarketContextTest(unittest.TestCase):
    def test_position_uses_latest_hour_not_a_single_trade(self):
        # A flat week; one live trade far below it shouldn't make the item look "at its low".
        c = analyse(replace(BASE, low=60, high=110), steady_week(1))
        self.assertAlmostEqual(c.position, 0.5)
        self.assertNotIn("low", labels(c))

    def summary(self, near_low_share):
        return merch.MarketSummary(items=100, median_trend=-0.02, near_low_share=near_low_share, near_high_share=0.1)

    def test_broad_dip_softens_the_low_signal(self):
        series = steady_week(1, high=280, low=270, step=-1)
        it = replace(BASE, high=112, low=102)
        alone = merch.analyse(it, market(it), series, S, self.summary(0.2))
        broad = merch.analyse(it, market(it), series, S, self.summary(0.45))
        self.assertIn("so are 45% of items", next(s.detail for s in broad.signals if s.key == "low"))
        self.assertGreater(alone.adjusted_profit, broad.adjusted_profit)  # no dip bonus in a broad dip
        self.assertAlmostEqual(broad.trend_vs_market, broad.trend_24h + 0.02)

    def test_market_summary(self):
        falling = steady_week(1, high=280, low=270, step=-1)
        flat = steady_week(2)
        it1 = replace(BASE, daily_volume=24_000)
        it2 = replace(BASE, id=2, name="Flat")
        summary = merch.market_summary(market(it1, it2), {**falling, **flat}, S)
        self.assertEqual(summary.items, 2)
        self.assertAlmostEqual(summary.near_low_share, 0.5)
        self.assertTrue(summary.broad_dip)  # half the market at its low is well above the ~20% norm
