import time
import unittest
from dataclasses import replace

from backend.engine import activities, inventory, market as market_mod
from backend.engine.market import ItemMarket, Market
from backend.engine.model import ActivitySpec, Flag, Leg, Limit, Risk, evaluate, ge_tax
from backend.engine.ranking import Filters, SortKey, rank
from backend.engine.settings import PriceMode, Settings
from backend.ingest import mapping, prices, recipes
from backend.ingest.recipes import Overrides
from tests.helpers import FakeFetch, load_fixture, memory_db

NOW = 1_800_000_000
S = Settings()


def item(id, name, high, low, volume=1_000_000, limit=10_000, members=True, **kw):
    defaults = dict(high_time=NOW - 60, low_time=NOW - 60, day_avg_high=high, day_avg_low=low,
                    hour_avg_high=high, hour_avg_low=low, highalch=None, volatility=0.01)
    defaults.update(kw)
    return ItemMarket(id=id, name=name, members=members, buy_limit=limit, high=high, low=low,
                      daily_volume=volume, **defaults)


def market(*items):
    return Market(items={i.id: i for i in items}, now=NOW)


GLASS = item(1, "Molten glass", high=100, low=95)
ORB = item(2, "Unpowered orb", high=210, low=200)


def orb_spec(**kw):
    defaults = dict(key="recipe:orb", type="recipe", name="Unpowered orb",
                    inputs=(Leg("Molten glass", 1, 1),), outputs=(Leg("Unpowered orb", 2, 1),),
                    ticks=3, skills=(("Crafting", 46),))
    defaults.update(kw)
    return ActivitySpec(**defaults)


class TaxTest(unittest.TestCase):
    def test_rules(self):
        self.assertEqual(ge_tax(49, S), 0)
        self.assertEqual(ge_tax(50, S), 1)
        self.assertEqual(ge_tax(1_234, S), 24)
        self.assertEqual(ge_tax(1_000_000_000, S), 5_000_000)
        self.assertEqual(ge_tax(12_000_000, S, item_id=13190), 0)  # bonds are exempt


class ProfitTest(unittest.TestCase):
    def test_instant_buys_high_sells_low(self):
        r = evaluate(orb_spec(), market(GLASS, ORB), S)
        self.assertEqual((r.input_cost, r.gross_revenue, r.tax), (100, 200, 4))
        self.assertEqual(r.profit, 96)
        self.assertAlmostEqual(r.roi, 0.96)

    def test_patient_buys_low_sells_high(self):
        r = evaluate(orb_spec(), market(GLASS, ORB), replace(S, price_mode=PriceMode.PATIENT))
        self.assertEqual(r.profit, 210 - 4 - 95)

    def test_average_uses_hourly_averages(self):
        glass = replace(GLASS, hour_avg_high=90)
        r = evaluate(orb_spec(), market(glass, ORB), replace(S, price_mode=PriceMode.AVERAGE))
        self.assertEqual(r.input_cost, 90)

    def test_coins_cost_face_value(self):
        spec = orb_spec(inputs=(Leg("Molten glass", 1, 1), Leg("Coins", None, 5, "coins")))
        self.assertEqual(evaluate(spec, market(GLASS, ORB), S).input_cost, 105)

    def test_fixed_revenue_is_untaxed(self):
        spec = orb_spec(outputs=(), fixed_revenue=300)
        r = evaluate(spec, market(GLASS), S)
        self.assertEqual((r.tax, r.profit), (0, 200))

    def test_missing_price_is_not_ranked(self):
        r = evaluate(orb_spec(), market(GLASS, replace(ORB, low=None)), S)
        self.assertIn(Flag.MISSING_PRICE, r.flags)
        self.assertFalse(r.ranked)


class RateTest(unittest.TestCase):
    def test_trip_model(self):
        # 14 actions of 1 tick, then a 10-tick bank: 14 actions per 24 ticks.
        spec = orb_spec(ticks=1, actions_per_trip=14, trip_overhead_ticks=10)
        r = evaluate(spec, market(GLASS, ORB), S)
        self.assertAlmostEqual(r.actions_per_hour, 6000 * 14 / 24 * 0.9)

    def test_no_banking_needed(self):
        r = evaluate(orb_spec(ticks=5, efficiency=1.0), market(GLASS, ORB), S)
        self.assertAlmostEqual(r.actions_per_hour, 1200)

    def test_fixed_rate_override(self):
        r = evaluate(orb_spec(ticks=None, fixed_rate=500), market(GLASS, ORB), S)
        self.assertEqual(r.actions_per_hour, 500)

    def test_unknown_ticks(self):
        r = evaluate(orb_spec(ticks=None), market(GLASS, ORB), S)
        self.assertIn(Flag.NO_RATE, r.flags)
        self.assertIsNotNone(r.profit)
        self.assertFalse(r.ranked)

    def test_estimated_flag(self):
        r = evaluate(orb_spec(ticks_estimated=True), market(GLASS, ORB), S)
        self.assertIn(Flag.ESTIMATED_RATE, r.flags)

    def test_speed_limited(self):
        r = evaluate(orb_spec(), market(GLASS, ORB), S)
        self.assertEqual(r.limiting_factor, Limit.SPEED)
        self.assertAlmostEqual(r.gp_hr, 96 * 1800)

    def test_buy_limit(self):
        r = evaluate(orb_spec(), market(replace(GLASS, buy_limit=400), ORB), S)
        self.assertEqual(r.limiting_factor, Limit.BUY_LIMIT)
        self.assertAlmostEqual(r.effective_actions, 100)  # 400 per 4 hours
        self.assertAlmostEqual(r.gp_hr_raw, 96 * 1800)

    def test_liquidity(self):
        r = evaluate(orb_spec(), market(GLASS, replace(ORB, daily_volume=2_400)), S)
        self.assertEqual(r.limiting_factor, Limit.LIQUIDITY)
        self.assertAlmostEqual(r.effective_actions, 10)  # 10% of 100/hour

    def test_caps_list_every_limit(self):
        r = evaluate(orb_spec(), market(replace(GLASS, buy_limit=400), ORB), S)
        caps = {(c.limit, c.item): c.actions_per_hour for c in r.caps}
        self.assertAlmostEqual(caps[(Limit.SPEED, None)], 1800)
        self.assertAlmostEqual(caps[(Limit.BUY_LIMIT, "Molten glass")], 100)
        self.assertAlmostEqual(caps[(Limit.LIQUIDITY, "Unpowered orb")], 0.1 * 1_000_000 / 24)
        self.assertEqual(r.efficiency, 0.9)

    def test_day_profit(self):
        r = evaluate(orb_spec(), market(GLASS, replace(ORB, day_avg_low=180)), S)
        self.assertEqual(r.day_profit, 180 - 3 - 100)

    def test_daily_potential_thin_market(self):
        # The Belle's folly case: a fast action on a thin input market. 2,400 a day trade, so
        # 10% is 240 a day, but only 10 an hour, so GP/hr badly undersells the method.
        r = evaluate(orb_spec(ticks=1), market(replace(GLASS, daily_volume=2_400), ORB), S)
        self.assertAlmostEqual(r.effective_actions, 10)
        self.assertAlmostEqual(r.daily_units, 240)
        self.assertAlmostEqual(r.daily_profit, 240 * 96)
        self.assertEqual((r.daily_limit.limit, r.daily_limit.item), (Limit.LIQUIDITY, "Molten glass"))
        self.assertAlmostEqual(r.active_minutes, 240 / r.actions_per_hour * 60)

    def test_daily_buy_limit_is_six_windows(self):
        r = evaluate(orb_spec(), market(replace(GLASS, buy_limit=400), ORB), S)
        self.assertAlmostEqual(r.daily_units, 2400)
        self.assertEqual(r.daily_limit.limit, Limit.BUY_LIMIT)

    def test_daily_is_capped_by_playing_all_day(self):
        r = evaluate(orb_spec(), market(GLASS, ORB), S)  # huge markets, no limits
        self.assertAlmostEqual(r.daily_units, r.actions_per_hour * 24)
        self.assertEqual(r.daily_limit.limit, Limit.SPEED)

    def test_capital_per_hour(self):
        r = evaluate(orb_spec(), market(GLASS, ORB), S)
        self.assertAlmostEqual(r.capital_per_hour, 100 * 1800)


class VolumeFilterTest(unittest.TestCase):
    def test_thresholds_scale_with_price(self):
        self.assertEqual(S.min_daily_volume(5), 500)
        self.assertEqual(S.min_daily_volume(10_000), 50)
        self.assertEqual(S.min_daily_volume(250_000), 10)
        self.assertEqual(S.min_daily_volume(5_000_000), 3)

    def test_illiquid_input(self):
        r = evaluate(orb_spec(), market(replace(GLASS, daily_volume=499), ORB), S)
        self.assertFalse(r.liquid)
        self.assertIn(Flag.ILLIQUID, r.flags)

    def test_expensive_items_need_less_volume(self):
        gem = item(3, "Zenyte", high=10_000_000, low=9_900_000, volume=4)
        amulet = item(4, "Zenyte amulet", high=12_000_000, low=11_900_000, volume=5)
        spec = orb_spec(inputs=(Leg("Zenyte", 3, 1),), outputs=(Leg("Zenyte amulet", 4, 1),))
        r = evaluate(spec, market(gem, amulet), S)
        self.assertTrue(r.liquid)
        self.assertIn(Flag.LOW_VOLUME, r.flags)  # under 2 × the threshold of 3


class RiskTest(unittest.TestCase):
    def test_low(self):
        self.assertEqual(evaluate(orb_spec(), market(GLASS, ORB), S).risk, Risk.LOW)

    def test_thin_roi_is_high(self):
        # The "100m to make 1m" case.
        bow = item(5, "Crossbow", high=100_000_000, low=99_000_000)
        cbow = item(6, "Fancy crossbow", high=103_500_000, low=103_000_000, volatility=0.001)
        spec = orb_spec(inputs=(Leg("Crossbow", 5, 1),), outputs=(Leg("Fancy crossbow", 6, 1),))
        r = evaluate(spec, market(bow, cbow), S)
        self.assertLess(r.roi, 0.02)
        self.assertEqual(r.risk, Risk.HIGH)

    def test_breakeven_inside_volatility_is_high(self):
        r = evaluate(orb_spec(), market(GLASS, replace(ORB, volatility=0.6)), S)
        self.assertEqual(r.risk, Risk.HIGH)
        self.assertAlmostEqual(r.gp_hr_risk_adjusted, r.gp_hr * r.breakeven_move / 0.6)

    def test_medium(self):
        r = evaluate(orb_spec(), market(GLASS, replace(ORB, volatility=0.3)), S)
        self.assertEqual(r.risk, Risk.MEDIUM)  # break-even 48% is under 2 × 30%


class FlagTest(unittest.TestCase):
    def test_stale(self):
        r = evaluate(orb_spec(), market(GLASS, replace(ORB, low_time=NOW - 3600)), S)
        self.assertIn(Flag.STALE_PRICE, r.flags)
        self.assertEqual(r.price_age, 3600)

    def test_margin_spike(self):
        orb = replace(ORB, low=400, day_avg_low=200)
        self.assertIn(Flag.MARGIN_SPIKE, evaluate(orb_spec(), market(GLASS, orb), S).flags)
        self.assertNotIn(Flag.MARGIN_SPIKE, evaluate(orb_spec(), market(GLASS, ORB), S).flags)

    def test_f2p_needs_f2p_recipe_and_items(self):
        free_glass, free_orb = replace(GLASS, members=False), replace(ORB, members=False)
        self.assertTrue(evaluate(orb_spec(members=False), market(free_glass, free_orb), S).f2p)
        self.assertFalse(evaluate(orb_spec(members=False), market(free_glass, ORB), S).f2p)
        self.assertFalse(evaluate(orb_spec(), market(free_glass, free_orb), S).f2p)


class InventoryTest(unittest.TestCase):
    def test_stackable_names(self):
        for name in ("Nature rune", "Coins", "Rune arrow", "Feather", "Ranarr seed",
                     "Varrock teleport (tablet)", "Steel cannonball", "Bronze javelin(p)", "Arrow shaft"):
            self.assertTrue(inventory.is_stackable(name), name)
        for name in ("Rune platebody", "Runite bar", "Grimy ranarr weed", "Vial of water"):
            self.assertFalse(inventory.is_stackable(name), name)

    def test_stackable_overrides(self):
        self.assertTrue(inventory.is_stackable("Molten glass", add={"Molten glass"}))
        self.assertFalse(inventory.is_stackable("Feather", remove={"Feather"}))

    def test_actions_per_trip(self):
        self.assertEqual(inventory.actions_per_trip(2, 1, None), 14)
        self.assertEqual(inventory.actions_per_trip(1, 1, "Glassblowing pipe"), 27)
        self.assertEqual(inventory.actions_per_trip(0, 0, None), None)
        self.assertEqual(inventory.actions_per_trip(30, 1, None), 1)


class RankTest(unittest.TestCase):
    def setUp(self):
        m = market(GLASS, ORB, replace(GLASS, id=7, name="Cheap glass", members=False, high=50),
                   replace(ORB, id=8, name="Free orb", members=False), replace(ORB, id=9, name="Thin orb", daily_volume=10))
        self.results = [
            evaluate(orb_spec(), m, S),
            evaluate(orb_spec(key="f2p", name="Free orb", members=False, skills=(("Crafting", 10),),
                              inputs=(Leg("Cheap glass", 7, 1),), outputs=(Leg("Free orb", 8, 1),)), m, S),
            evaluate(orb_spec(key="thin", name="Thin orb", outputs=(Leg("Thin orb", 9, 1),)), m, S),
            evaluate(orb_spec(key="loss", name="Loss", inputs=(Leg("Unpowered orb", 2, 1),),
                              outputs=(Leg("Molten glass", 1, 1),)), m, S),
        ]

    def names(self, **kw):
        sort = kw.pop("sort", SortKey.GP_HR)
        return [r.spec.name for r in rank(self.results, Filters(**kw), sort)]

    def test_default_hides_losses_and_illiquid(self):
        self.assertEqual(self.names(), ["Free orb", "Unpowered orb"])

    def test_include_illiquid(self):
        self.assertIn("Thin orb", self.names(include_illiquid=True))

    def test_f2p_only(self):
        self.assertEqual(self.names(f2p_only=True), ["Free orb"])

    def test_player_levels(self):
        self.assertEqual(self.names(player_levels={"crafting": 20}), ["Free orb"])
        self.assertEqual(len(self.names(player_levels={"crafting": 99})), 2)

    def test_min_daily_volume(self):
        # Free orb and Unpowered orb trade 1m a day; Thin orb trades 10.
        self.assertEqual(self.names(include_illiquid=True, min_daily_volume=1000), ["Free orb", "Unpowered orb"])
        self.assertIn("Thin orb", self.names(include_illiquid=True, min_daily_volume=10))

    def test_sort_by_daily(self):
        for r in self.results:
            r.daily_profit = {"Unpowered orb": 10, "Free orb": 5}.get(r.spec.name, 0)
        self.assertEqual(self.names(sort=SortKey.DAILY), ["Unpowered orb", "Free orb"])

    def test_search(self):
        self.assertEqual(self.names(search="unpowered"), ["Unpowered orb"])


class IntegrationTest(unittest.TestCase):
    """Market loading and activity building against a real (in-memory) database."""

    def setUp(self):
        self.conn = memory_db()
        fetch = FakeFetch({"/mapping": load_fixture("mapping.json"),
                           "api.php": load_fixture("recipe_bucket.json")})
        mapping.refresh(self.conn, fetch)
        recipes.refresh(self.conn, fetch, Overrides())
        self.now = (int(time.time()) // 3600) * 3600
        for i in range(48):
            price = 100 if i % 2 else 120
            prices.store_hour(self.conn, {"timestamp": self.now - i * 3600, "data": {
                "567": {"avgHighPrice": price, "highPriceVolume": 10, "avgLowPrice": price, "lowPriceVolume": 30}}})

    def test_market_aggregates(self):
        orb = market_mod.load(self.conn, self.now).get(567)
        self.assertEqual(orb.daily_volume, 24 * 40)
        self.assertAlmostEqual(orb.day_avg_high, 110)
        self.assertAlmostEqual(orb.volatility, 10 / 110)
        self.assertEqual(orb.hour_avg_high, 120)

    def test_recipe_specs(self):
        specs = {s.key.split("|")[0]: s for s in activities.recipe_specs(self.conn, S, Overrides())}
        self.assertNotIn("recipe:Burnt pie", specs)  # not GE-viable
        orb = specs["recipe:Unpowered orb"]
        self.assertEqual((orb.ticks, orb.actions_per_trip, orb.trip_overhead_ticks), (3, 27, 10))
        anti = specs["recipe:Antipoison#4 dose"]
        self.assertEqual((anti.ticks, anti.ticks_estimated), (2, True))

    def test_travel_skill_has_no_ticks(self):
        settings = replace(S, travel_skills=frozenset({"Crafting"}))
        specs = {s.key.split("|")[0]: s for s in activities.recipe_specs(self.conn, settings, Overrides())}
        self.assertIsNone(specs["recipe:Unpowered orb"].ticks)

    def test_alch_specs(self):
        m = market_mod.load(self.conn, self.now)
        nature = ItemMarket(id=561, name="Nature rune", members=False, buy_limit=18000, highalch=0)
        m.items[561] = nature
        specs = {s.name: s for s in activities.alch_specs(m, S)}
        self.assertEqual(specs["Unpowered orb"].fixed_revenue, 60)
        self.assertEqual(specs["Unpowered orb"].inputs[1].item_id, 561)
        self.assertNotIn("Molten glass", specs)  # no alch value


if __name__ == "__main__":
    unittest.main()
