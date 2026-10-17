"""Flipping, decanting, item sets and the passive rate mode."""

import unittest
from dataclasses import replace

from backend import db
from backend.engine import activities
from backend.engine.model import ActivitySpec, Flag, Leg, Limit, evaluate
from backend.engine.settings import PriceMode, Settings
from backend.ingest import sets
from backend.ingest.recipes import Overrides
from tests.helpers import FakeFetch
from tests.test_engine import NOW, item, market

S = Settings()

SET_PAGE = """{{Infobox Item|name = Rune armour set (lg)}}
'''Rune armour set (lg)''' is an item set.
==Components==
{{CostTableHead}}
{{CostLine|Rune full helm}}
{{CostLine|Rune platebody}}
{{CostLine | Rune arrow | 100}}
{{CostTableBottom|total=y}}

== Bonuses ==
{{CostLine|Not a component}}
"""


class SetParsingTest(unittest.TestCase):
    def test_components_section_only(self):
        self.assertEqual(sets.parse_components(SET_PAGE),
                         [("Rune full helm", 1), ("Rune platebody", 1), ("Rune arrow", 100)])

    def test_no_components(self):
        self.assertEqual(sets.parse_components("{{Infobox Item}} no section"), [])

    def test_refresh_follows_normalised_titles(self):
        conn = db.connect(":memory:")
        conn.executemany("INSERT INTO items (id, name, members) VALUES (?, ?, 0)",
                         [(1, "Rune armour set (lg)"), (2, "Rune full helm"), (3, "Rune platebody")])
        fetch = FakeFetch({"api.php": {"query": {
            "normalized": [{"from": "Rune armour set (lg)", "to": "Rune Armour Set (lg)"}],
            "pages": [{"title": "Rune Armour Set (lg)", "revisions": [{"slots": {"main": {"content": SET_PAGE}}}]}],
        }}})
        stats = sets.refresh(conn, fetch)
        self.assertEqual((stats["sets"], stats["components"]), (1, 3))
        rows = conn.execute("SELECT name, item_id FROM item_sets ORDER BY position").fetchall()
        self.assertEqual([tuple(r) for r in rows], [("Rune full helm", 2), ("Rune platebody", 3), ("Rune arrow", None)])


class PassiveTest(unittest.TestCase):
    def test_no_speed_cap(self):
        thing = item(1, "Thing", high=110, low=100, limit=400)
        spec = ActivitySpec(key="k", type="flip", name="Thing", inputs=(Leg("Thing", 1, 1),),
                            outputs=(Leg("Thing", 1, 1),), passive=True, price_mode=PriceMode.PATIENT)
        r = evaluate(spec, market(thing), S)
        self.assertNotIn(Limit.SPEED, {c.limit for c in r.caps})
        self.assertEqual(sum(c.limit is Limit.LIQUIDITY for c in r.caps), 1)  # same item bought and sold
        self.assertEqual(r.limiting_factor, Limit.BUY_LIMIT)
        self.assertAlmostEqual(r.effective_actions, 100)
        self.assertEqual(r.actions_per_hour, r.effective_actions)
        self.assertEqual(r.profit, 110 - 2 - 100)  # patient pricing even though the user's mode is instant
        self.assertIsNone(r.efficiency)

    def test_nothing_to_cap(self):
        spec = ActivitySpec(key="k", type="set", name="Coins only", inputs=(Leg("Coins", None, 5, "coins"),),
                            fixed_revenue=10, passive=True)
        r = evaluate(spec, market(), S)
        self.assertIn(Flag.NO_RATE, r.flags)
        self.assertIsNone(r.actions_per_hour)
        self.assertFalse(r.ranked)


class FlipTest(unittest.TestCase):
    def test_specs(self):
        m = market(
            item(1, "Wide", high=120, low=100),
            item(2, "Crossed", high=100, low=100),
            item(3, "Old quote", high=120, low=100, low_time=NOW - 3 * 3600),
        )
        specs = activities.flip_specs(m, S)
        self.assertEqual([s.name for s in specs], ["Wide"])
        r = evaluate(specs[0], m, S)
        self.assertEqual(r.profit, 120 - 2 - 100)
        self.assertEqual(r.spec.type, "flip")

    def test_f2p_follows_item(self):
        m = market(item(1, "Free", high=120, low=100, members=False), item(2, "Paid", high=120, low=100))
        f2p = {s.name: evaluate(s, m, S).f2p for s in activities.flip_specs(m, S)}
        self.assertEqual(f2p, {"Free": True, "Paid": False})


class DecantTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        rows = [
            (10, "Prayer potion(4)", "4 doses of prayer restore potion."),
            (11, "Prayer potion(3)", "3 doses of prayer restore potion."),
            (12, "Prayer potion(1)", "1 dose of prayer restore potion."),
            (20, "Amulet of glory(4)", "A dragonstone amulet with 4 magic charges."),
            (21, "Amulet of glory(6)", "A dragonstone amulet with 6 magic charges."),
            (30, "Ring of charm(1)", "A ring."),
            (31, "Ring of charm(2)", "A ring."),
            (40, "Antifire mix(1)", "One dose of fishy anti-firebreath potion."),
            (41, "Antifire mix(2)", "Two doses of fishy anti-firebreath potion."),
            (50, "Guthix rest(1)", "A cup of Guthix Rest."),
            (51, "Guthix rest(4)", "A cup of Guthix Rest."),
        ]
        self.conn.executemany("INSERT INTO items (id, name, members, examine) VALUES (?, ?, 1, ?)", rows)

    def test_families(self):
        families = activities.potion_families(self.conn, Overrides(decant_include={"Guthix rest"}))
        self.assertEqual(families, {"Prayer potion": {4: 10, 3: 11, 1: 12}, "Guthix rest": {1: 50, 4: 51}})

    def test_exclude(self):
        families = activities.potion_families(self.conn, Overrides(decant_exclude={"Prayer potion"}))
        self.assertNotIn("Prayer potion", families)

    def test_specs_balance_doses(self):
        m = market(item(10, "Prayer potion(4)", 900, 880), item(11, "Prayer potion(3)", 600, 590),
                   item(12, "Prayer potion(1)", 250, 240), item(229, "Vial", 5, 3))
        specs = {s.key: s for s in activities.decant_specs(self.conn, m, S, Overrides())}
        up = specs["decant:11:10"]  # (3) -> (4)
        self.assertEqual(([(l.name, l.quantity) for l in up.inputs], up.outputs[0].quantity),
                         ([("Prayer potion(3)", 4)], 3))
        down = specs["decant:10:12"]  # (4) -> (1) needs three extra vials
        self.assertEqual([(l.name, l.quantity) for l in down.inputs], [("Prayer potion(4)", 1), ("Vial", 3)])
        self.assertEqual(down.outputs[0].quantity, 4)
        self.assertTrue(up.passive)


class SetSpecTest(unittest.TestCase):
    def test_both_directions_and_untradeable_pieces(self):
        conn = db.connect(":memory:")
        conn.executemany("INSERT INTO item_sets (set_id, position, name, item_id, quantity) VALUES (?, ?, ?, ?, ?)", [
            (1, 0, "Helm", 2, 1), (1, 1, "Body", 3, 1),
            (9, 0, "Helm", 2, 1), (9, 1, "Untradeable bit", None, 1),
        ])
        m = market(item(1, "Armour set", 1000, 990), item(2, "Helm", 300, 290), item(3, "Body", 600, 590),
                   item(9, "Odd set", 500, 490))
        specs = {s.key: s for s in activities.set_specs(conn, m)}
        self.assertEqual(set(specs), {"set:combine:1", "set:split:1"})
        combine = evaluate(specs["set:combine:1"], m, S)
        self.assertEqual(combine.profit, 990 - 19 - 900)
        split = evaluate(specs["set:split:1"], m, S)
        self.assertEqual(split.profit, (290 - 5) + (590 - 11) - 1000)


if __name__ == "__main__":
    unittest.main()
