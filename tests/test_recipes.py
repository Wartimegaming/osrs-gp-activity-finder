import unittest

from backend.ingest import mapping, recipes
from backend.ingest.recipes import Overrides
from tests.helpers import FakeFetch, load_fixture, memory_db


def load(overrides: Overrides | None = None):
    conn = memory_db()
    fetch = FakeFetch({"/mapping": load_fixture("mapping.json"),
                       "api.php": load_fixture("recipe_bucket.json")})
    mapping.refresh(conn, fetch)
    stats = recipes.refresh(conn, fetch, overrides or Overrides())
    return conn, stats


def recipe(conn, page_name_sub, variant=None):
    sql = "SELECT * FROM recipes WHERE page_name_sub = ?"
    params = [page_name_sub]
    if variant:
        sql += " AND variant = ?"
        params.append(variant)
    return conn.execute(sql, params).fetchone()


class ParseTicksTest(unittest.TestCase):
    def test_values(self):
        self.assertEqual(recipes.parse_ticks("3"), (3, "wiki"))
        self.assertEqual(recipes.parse_ticks("0"), (None, "zero"))
        for raw in ("", "Varies", "na", None):
            self.assertEqual(recipes.parse_ticks(raw), (None, "unknown"))


class RefreshTest(unittest.TestCase):
    def test_skips_non_item_recipes(self):
        conn, stats = load()
        self.assertEqual(stats["bucket_rows"], 6)
        self.assertEqual(stats["item_recipes"], 5)
        self.assertIsNone(recipe(conn, "Cairn Isle"))

    def test_simple_recipe(self):
        conn, _ = load()
        orb = recipe(conn, "Unpowered orb")
        self.assertEqual(orb["output_item_id"], 567)
        self.assertEqual(orb["ticks"], 3)
        self.assertEqual(orb["tools"], "Glassblowing pipe")
        self.assertTrue(orb["ge_viable"])
        self.assertFalse(orb["f2p"])  # the recipe is members-only
        skill = conn.execute("SELECT * FROM recipe_skills WHERE recipe_key = ?",
                             (orb["recipe_key"],)).fetchone()
        self.assertEqual((skill["skill"], skill["level"], skill["experience"], skill["boostable"]),
                         ("Crafting", 46, 52.5, 1))

    def test_variants_on_one_page_are_kept_separately(self):
        conn, _ = load()
        normal = recipe(conn, "Bronze bar", "Normal furnace")
        blast = recipe(conn, "Bronze bar", "Blast furnace")
        self.assertNotEqual(normal["recipe_key"], blast["recipe_key"])
        self.assertTrue(normal["f2p"])
        self.assertFalse(blast["f2p"])
        self.assertEqual(blast["ticks_source"], "unknown")

    def test_f2p_requires_every_item_to_be_f2p(self):
        conn, _ = load()
        # The recipe is flagged F2P on the wiki, but Limpwurt root is a members item.
        self.assertFalse(recipe(conn, "Antipoison#4 dose")["f2p"])

    def test_coins_are_tradeable_materials(self):
        conn, _ = load()
        anti = recipe(conn, "Antipoison#4 dose")
        self.assertTrue(anti["ge_viable"])
        self.assertEqual(anti["ticks_source"], "zero")
        coins = conn.execute("SELECT * FROM recipe_materials WHERE recipe_key = ? AND name = 'Coins'",
                             (anti["recipe_key"],)).fetchone()
        self.assertEqual((coins["kind"], coins["item_id"], coins["quantity"]), ("coins", None, 5.0))

    def test_untradeable_recipes_are_not_viable(self):
        conn, _ = load()
        pie = recipe(conn, "Burnt pie")
        self.assertFalse(pie["ge_viable"])
        self.assertIsNone(pie["output_item_id"])
        material = conn.execute("SELECT * FROM recipe_materials WHERE recipe_key = ?",
                                (pie["recipe_key"],)).fetchone()
        self.assertEqual((material["kind"], material["quantity"]), ("untradeable", 0.5))
        names = [r["name"] for r in recipes.unmatched_names(conn)]
        self.assertCountEqual(names, ["Burnt pie", "Uncooked pie"])

    def test_refresh_replaces_previous_data(self):
        conn, _ = load()
        fetch = FakeFetch({"api.php": load_fixture("recipe_bucket.json")})
        recipes.refresh(conn, fetch, Overrides())
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM recipes").fetchone()[0], 5)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM recipe_materials").fetchone()[0], 8)


class OverridesTest(unittest.TestCase):
    def test_alias_makes_untradeable_name_match(self):
        conn, _ = load(Overrides(aliases={"Uncooked pie": "Molten glass", "Burnt pie": "Unpowered orb"}))
        self.assertTrue(recipe(conn, "Burnt pie")["ge_viable"])

    def test_recipe_override(self):
        overrides = Overrides(recipes={"Bronze bar": {"key": "Bronze bar", "ticks": 4,
                                                      "efficiency": 0.7, "note": "test"}})
        conn, _ = load(overrides)
        blast = recipe(conn, "Bronze bar", "Blast furnace")
        self.assertEqual((blast["ticks"], blast["ticks_source"]), (4, "override"))
        self.assertEqual((blast["efficiency"], blast["note"]), (0.7, "test"))

    def test_exclude(self):
        overrides = Overrides(recipes={"Unpowered orb": {"key": "Unpowered orb", "exclude": True}})
        conn, _ = load(overrides)
        self.assertTrue(recipe(conn, "Unpowered orb")["excluded"])

    def test_shipped_overrides_file_parses(self):
        Overrides.load()


class PaginationTest(unittest.TestCase):
    def test_follows_offsets_until_short_page(self):
        from backend import config
        pages = {0: [{"n": i} for i in range(config.BUCKET_PAGE_SIZE)], config.BUCKET_PAGE_SIZE: [{"n": -1}]}

        def respond(params):
            offset = int(params["query"].split(".offset(")[1].split(")")[0])
            return {"bucket": pages[offset]}

        rows = recipes.fetch_all(FakeFetch({"api.php": respond}))
        self.assertEqual(len(rows), config.BUCKET_PAGE_SIZE + 1)

    def test_bucket_error_raises(self):
        with self.assertRaises(RuntimeError):
            recipes.fetch_all(FakeFetch({"api.php": {"error": "Invalid field name"}}))


if __name__ == "__main__":
    unittest.main()
