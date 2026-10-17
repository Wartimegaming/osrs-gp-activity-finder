"""NPC shops, two-step chains and the 7-day consistency score."""

import unittest
from dataclasses import replace

from backend import db
from backend.engine import activities, chains, history
from backend.engine.model import ActivitySpec, Flag, Leg, evaluate
from backend.engine.ranking import Filters, _best_shop_per_item, rank
from backend.engine.settings import PriceMode, Settings
from backend.ingest import shops
from backend.ingest.recipes import Overrides
from tests.helpers import FakeFetch
from tests.test_engine import item, market

S = Settings()


class ShopIngestTest(unittest.TestCase):
    def test_refresh(self):
        conn = db.connect(":memory:")
        conn.executemany("INSERT INTO items (id, name, members) VALUES (?, ?, 0)", [(1, "Feather"), (2, "Rune")])
        storeline = {"bucket": [
            {"sold_by": "Fish shop", "sold_item": "Feather", "store_sell_price": "2", "store_currency": "Coins",
             "store_delta": "10", "store_stock": "1,000", "store_sell_multiplier": "1000", "restock_time": "1"},
            {"sold_by": "Points shop", "sold_item": "Rune", "store_sell_price": "5", "store_currency": "Points"},
            {"sold_by": "Fish shop", "sold_item": "Not on GE", "store_sell_price": "5", "store_currency": "Coins"},
            {"sold_by": "Magic shop", "sold_item": "Rune", "store_sell_price": "N/A", "store_currency": "Coins"},
            {"sold_by": "Magic shop", "sold_item": "Rune", "store_sell_price": "17", "store_currency": "Coins",
             "store_stock": "∞", "store_delta": "0"},
        ]}
        infobox = {"bucket": [{"page_name": "Fish shop", "location": "[[Port Sarim]]"},
                              {"page_name": "Magic shop", "location": "[[Shilo Village (location)|Shilo Village]] centre"}]}
        pages = {"query": {"pages": [
            {"title": "Fish shop", "revisions": [{"slots": {"main": {"content": "{{Infobox Shop\n|members = No\n}}"}}}]},
            {"title": "Magic shop", "revisions": [{"slots": {"main": {"content": "{{Infobox Shop|members=Yes}}"}}}]},
        ]}}

        def respond(params):
            query = params.get("query", "")
            if "storeline" in query:
                return storeline
            if "infobox_shop" in query:
                return infobox
            return pages

        stats = shops.refresh(conn, FakeFetch({"api.php": respond}))
        self.assertEqual(stats["resellable"], 2)
        rows = {r["shop"]: r for r in conn.execute("SELECT * FROM shop_items")}
        self.assertEqual((rows["Fish shop"]["stock"], rows["Fish shop"]["members"], rows["Fish shop"]["location"]),
                         (1000, 0, "Port Sarim"))
        self.assertEqual((rows["Magic shop"]["stock"], rows["Magic shop"]["members"], rows["Magic shop"]["location"]),
                         (None, 1, "Shilo Village centre"))


class ShopModelTest(unittest.TestCase):
    def test_price_climbs_until_unprofitable(self):
        # value 100, +10% of value per item bought: 100, 110, 120, ... stops before reaching 140.
        units, avg = activities.shop_units(100, 100, 100, 1000, stock=50, ge_net=140, cap=1000)
        self.assertEqual((units, avg), (4, (100 + 110 + 120 + 130) / 4))

    def test_stock_and_cap(self):
        self.assertEqual(activities.shop_units(5, 5, 0, 1000, stock=3, ge_net=50, cap=1000)[0], 3)
        self.assertEqual(activities.shop_units(5, 5, 0, 1000, stock=None, ge_net=50, cap=200)[0], 200)
        self.assertEqual(activities.shop_units(60, 60, 0, 1000, stock=10, ge_net=50, cap=200)[0], 0)

    def setUp(self):
        self.conn = db.connect(":memory:")
        self.conn.executemany("INSERT INTO items (id, name, members, value) VALUES (?, ?, 0, ?)",
                              [(1, "Chaos rune", 90), (2, "Raw shark", 300)])
        self.conn.executemany(
            "INSERT INTO shop_items (shop, item_id, item_name, price, stock, delta, sell_multiplier, members, location) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", [
                ("Rune shop", 1, "Chaos rune", 90, 250, 1, 1000, 0, "Varrock"),
                ("Other rune shop", 1, "Chaos rune", 90, 100, 1, 1000, 1, "Ardougne"),
                ("Fish shop", 2, "Raw shark", 300, 10, 10, 1000, 1, "Shilo"),
                ("Mixology Rewards", 2, "Raw shark", 1, None, 0, 1000, 1, None),
            ])
        self.market = market(item(1, "Chaos rune", high=105, low=100, members=False),
                             item(2, "Raw shark", high=900, low=880, members=True))

    def test_specs(self):
        specs = {s.key: s for s in activities.shop_specs(self.conn, self.market, S, Overrides())}
        self.assertNotIn("shop:Mixology Rewards:2", specs)  # reward shops are paid in points
        rune = specs["shop:Rune shop:1"]
        self.assertEqual((rune.type, rune.inputs[0].kind, rune.ticks_estimated, rune.members), ("shop", "coins", True, False))
        shark = specs["shop:Fish shop:2"]
        # Sharks don't stack: 10 per visit (the stock), then bank and hop.
        self.assertAlmostEqual(shark.fixed_rate, 6000 * 10 / (S.shop_bank_ticks + S.shop_hop_ticks) * S.efficiency)

    def test_excluded_shop(self):
        specs = activities.shop_specs(self.conn, self.market, S, Overrides(shop_exclude={"Fish shop"}))
        self.assertNotIn("shop:Fish shop:2", {s.key for s in specs})

    def test_best_shop_per_item(self):
        results = [evaluate(s, self.market, S) for s in activities.shop_specs(self.conn, self.market, S, Overrides())]
        kept = _best_shop_per_item(results)
        runes = [r for r in kept if r.spec.outputs[0].item_id == 1]
        # One F2P listing and one members listing survive; they aren't merged.
        self.assertEqual(sorted(r.spec.variant for r in runes), ["Other rune shop", "Rune shop"])


class ChainTest(unittest.TestCase):
    def setUp(self):
        self.m = market(
            item(1, "Sand", high=10, low=9),
            item(2, "Glass", high=100, low=95, limit=400),  # buying glass is buy-limited
            item(3, "Orb", high=260, low=250),
        )
        self.glass = ActivitySpec(key="recipe:glass", type="recipe", name="Glass", inputs=(Leg("Sand", 1, 1),),
                                  outputs=(Leg("Glass", 2, 1),), ticks=3)
        self.orb = ActivitySpec(key="recipe:orb", type="recipe", name="Orb", inputs=(Leg("Glass", 2, 1),),
                                outputs=(Leg("Orb", 3, 1),), ticks=3, skills=(("Crafting", 46),))

    def test_build_and_keep(self):
        results = [evaluate(s, self.m, S) for s in (self.glass, self.orb)]
        specs = chains.build(results, S)
        self.assertEqual(len(specs), 1)
        chain = specs[0]
        self.assertEqual([(l.name, l.quantity) for l in chain.inputs], [("Sand", 1)])
        self.assertAlmostEqual(chain.fixed_rate, 1 / (1 / 1800 + 1 / 1800))
        chain_result = evaluate(chain, self.m, S)
        by_key = {r.spec.key: r for r in results}
        kept = chains.keep_worthwhile([chain_result], by_key)
        # Orb alone is capped at 100/hr by glass's buy limit; making glass yourself avoids that.
        self.assertGreater(by_key["recipe:orb"].gp_hr, 0)
        self.assertEqual(kept, [chain_result])

    def test_not_kept_when_it_does_not_help(self):
        m = market(item(1, "Sand", high=10, low=9), item(2, "Glass", high=100, low=95),
                   item(3, "Orb", high=260, low=250))
        results = [evaluate(s, m, S) for s in (self.glass, self.orb)]
        chain_result = evaluate(chains.build(results, S)[0], m, S)
        self.assertEqual(chains.keep_worthwhile([chain_result], {r.spec.key: r for r in results}), [])

    def test_no_loops(self):
        undo = ActivitySpec(key="recipe:unglass", type="recipe", name="Sand", inputs=(Leg("Glass", 2, 1),),
                            outputs=(Leg("Sand", 1, 1),), ticks=3)
        results = [evaluate(s, self.m, S) for s in (self.glass, undo)]
        self.assertEqual(chains.build(results, S), [])


class ConsistencyTest(unittest.TestCase):
    SPEC = ActivitySpec(key="k", type="recipe", name="Orb", inputs=(Leg("Glass", 2, 1),),
                        outputs=(Leg("Orb", 3, 1),), ticks=3)

    def series(self, hours, profitable_every=1):
        glass, orb = {}, {}
        for h in range(hours):
            glass[h * 3600] = (100, 95)
            orb[h * 3600] = (210, 200) if h % profitable_every == 0 else (100, 90)
        return {2: glass, 3: orb}

    def test_share_and_median(self):
        c = history.score(self.SPEC, self.series(48, profitable_every=2), S)
        self.assertEqual(c.hours, 48)
        self.assertAlmostEqual(c.share, 0.5)

    def test_patient_uses_other_side(self):
        c = history.score(self.SPEC, self.series(30), replace(S, price_mode=PriceMode.PATIENT))
        self.assertEqual(c.median_profit, 210 - 4 - 95)

    def test_needs_a_day_of_shared_hours(self):
        self.assertIsNone(history.score(self.SPEC, self.series(23), S))
        self.assertIsNone(history.score(self.SPEC, {2: {0: (1, 1)}}, S))

    def test_min_consistency_filter(self):
        m = market(item(2, "Glass", 100, 95), item(3, "Orb", 210, 200))
        good, flaky = evaluate(self.SPEC, m, S), evaluate(replace(self.SPEC, key="k2", name="Flaky"), m, S)
        good.consistency, flaky.consistency = 0.95, 0.4
        self.assertEqual([r.spec.name for r in rank([good, flaky], Filters(min_consistency=0.8))], ["Orb"])


class ImplausibleTest(unittest.TestCase):
    def test_flag(self):
        m = market(item(2, "Glass", 10, 9), item(3, "Orb", 100_000, 99_000))
        r = evaluate(ConsistencyTest.SPEC, m, S)
        self.assertIn(Flag.IMPLAUSIBLE, r.flags)


if __name__ == "__main__":
    unittest.main()
