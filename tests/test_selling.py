"""Selling over a longer window, and recipes with ingredients bought from shops."""

import unittest
from dataclasses import replace

from backend import db
from backend.engine import supply
from backend.engine.model import ActivitySpec, Flag, Leg, Limit, evaluate
from backend.engine.settings import Settings
from backend.ingest.recipes import Overrides
from tests.test_engine import item, market

S = Settings()
DAY = replace(S, sell_window_hours=24)

# 2,400 orbs trade a day = 100/hr, so selling is capped at 10/hr unless sales can wait.
GLASS = item(1, "Glass", high=100, low=95, volume=1_000_000)
ORB = item(2, "Orb", high=210, low=200, volume=2_400, volatility=0.02)
SPEC = ActivitySpec(key="recipe:orb", type="recipe", name="Orb", inputs=(Leg("Glass", 1, 1),),
                    outputs=(Leg("Orb", 2, 1),), ticks=3)


def liquidity_cap(result, name):
    return next(c for c in result.caps if c.limit is Limit.LIQUIDITY and c.item == name)


class SellWindowTest(unittest.TestCase):
    def test_default_is_one_hour(self):
        r = evaluate(SPEC, market(GLASS, ORB), S, consistency=1.0)
        self.assertAlmostEqual(r.effective_actions, 10)
        self.assertNotIn(Flag.SLOW_SELL, r.flags)

    def test_steady_method_spreads_sales(self):
        r = evaluate(SPEC, market(GLASS, ORB), DAY, consistency=0.95)
        cap = liquidity_cap(r, "Orb")
        self.assertEqual(cap.window_hours, 24)
        self.assertAlmostEqual(cap.actions_per_hour, 240)
        self.assertAlmostEqual(r.effective_actions, 240)
        self.assertAlmostEqual(r.sell_hours, 24)
        self.assertIn(Flag.SLOW_SELL, r.flags)
        self.assertEqual(liquidity_cap(r, "Glass").window_hours, 1)  # buying can't wait

    def test_needs_consistency(self):
        self.assertEqual(liquidity_cap(evaluate(SPEC, market(GLASS, ORB), DAY, consistency=0.5), "Orb").window_hours, 1)
        self.assertEqual(liquidity_cap(evaluate(SPEC, market(GLASS, ORB), DAY, consistency=None), "Orb").window_hours, 1)

    def test_margin_must_cover_price_swings(self):
        # Break-even move is (200-4-100)/200 = 48%: fine at 20% volatility, not at 30%.
        ok = evaluate(SPEC, market(GLASS, replace(ORB, volatility=0.2)), DAY, consistency=1.0)
        swingy = evaluate(SPEC, market(GLASS, replace(ORB, volatility=0.3)), DAY, consistency=1.0)
        self.assertEqual(liquidity_cap(ok, "Orb").window_hours, 24)
        self.assertEqual(liquidity_cap(swingy, "Orb").window_hours, 1)

    def test_flips_never_wait(self):
        flip = ActivitySpec(key="flip:2", type="flip", name="Orb", inputs=(Leg("Orb", 2, 1),),
                            outputs=(Leg("Orb", 2, 1),), passive=True)
        r = evaluate(flip, market(replace(ORB, high=260)), DAY, consistency=1.0)
        self.assertTrue(all(c.window_hours == 1 for c in r.caps))

    def test_shop_bought_input_does_not_count_as_a_flip(self):
        shop = ActivitySpec(key="shop:x:2", type="shop", name="Orb", fixed_rate=1000,
                            inputs=(Leg("Orb", 2, 1, "shop", fixed_price=5, source="Shop"),),
                            outputs=(Leg("Orb", 2, 1),))
        r = evaluate(shop, market(ORB), DAY, consistency=1.0)
        self.assertEqual(liquidity_cap(r, "Orb").window_hours, 24)


class SupplyTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.conn.executemany("INSERT INTO items (id, name, members, value) VALUES (?, ?, 0, ?)",
                              [(1, "Glass", 1), (2, "Orb", 100)])
        self.conn.executemany(
            "INSERT INTO shop_items (shop, item_id, item_name, price, stock, delta, sell_multiplier, members, location) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", [
                ("Glass shop.", 1, "Glass", 10, None, 0, 1000, 0, "Town"),
                ("Pricey glass shop", 1, "Glass", 150, None, 0, 1000, 0, "Town"),  # dearer than the GE: ignored
            ])
        self.m = market(item(1, "Glass", high=100, low=95, limit=400), item(2, "Orb", high=260, low=250))

    def test_variant_swaps_ingredient_and_adds_buying_time(self):
        base = evaluate(SPEC, self.m, S)
        specs = supply.build([base], self.conn, self.m, S, Overrides())
        self.assertEqual(len(specs), 1)
        variant = specs[0]
        leg = variant.inputs[0]
        self.assertEqual((leg.kind, leg.source, leg.fixed_price), ("shop", "Glass shop.", 10))
        self.assertIn("Glass from Glass shop", variant.variant)
        # Unlimited stock, not stackable: 27 per bank trip of 100 ticks, at 90% efficiency.
        shop_rate = 6000 * 27 / 100 * 0.9
        self.assertAlmostEqual(variant.fixed_rate, 1 / (1 / 1800 + 1 / shop_rate))

    def test_kept_only_when_better_than_the_ge(self):
        base = evaluate(SPEC, self.m, S)
        variant = evaluate(supply.build([base], self.conn, self.m, S, Overrides())[0], self.m, S)
        # The GE route is capped at 100/hr by glass's buy limit; the shop has no buy limit.
        self.assertGreater(variant.gp_hr, base.gp_hr)
        self.assertEqual(supply.keep_worthwhile([variant], {base.spec.key: base}), [variant])
        worse = replace(variant, gp_hr=base.gp_hr - 1)
        self.assertEqual(supply.keep_worthwhile([worse], {base.spec.key: base}), [])


if __name__ == "__main__":
    unittest.main()
