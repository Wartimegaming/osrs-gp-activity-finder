import time
import unittest
import urllib.error
from unittest import mock

from fastapi.testclient import TestClient

from backend import config, db
from backend.api import hiscores, serialize
from backend.api.app import create_app
from backend.api.scheduler import JOBS, Scheduler
from backend.ingest import mapping, prices, recipes
from backend.ingest.recipes import Overrides
from tests.helpers import FakeFetch, load_fixture

HISCORES = {"name": "Some Player", "skills": [
    {"id": 0, "name": "Overall", "rank": 1, "level": 500, "xp": 1},
    {"id": 1, "name": "Crafting", "rank": 1, "level": 50, "xp": 1},
    {"id": 2, "name": "Sailing", "rank": -1, "level": -1, "xp": -1},
]}


class HiscoresTest(unittest.TestCase):
    def setUp(self):
        hiscores._cache.clear()

    def test_levels(self):
        result = hiscores.lookup("Some Player", FakeFetch({"index_lite.json": HISCORES}))
        self.assertEqual(result["levels"], {"crafting": 50, "sailing": 1})

    def test_cached(self):
        fetch = FakeFetch({"index_lite.json": HISCORES})
        hiscores.lookup("Some Player", fetch)
        hiscores.lookup("some player ", fetch)
        self.assertEqual(len(fetch.calls), 1)

    def test_not_found(self):
        def missing(url, params=None):
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        with self.assertRaises(hiscores.PlayerNotFound):
            hiscores.lookup("nobody", missing)


class SerializeTest(unittest.TestCase):
    def test_wiki_url(self):
        self.assertEqual(serialize.wiki_url("Antipoison#4 dose"),
                         "https://oldschool.runescape.wiki/w/Antipoison#4_dose")
        self.assertEqual(serialize.wiki_url("Unpowered orb"), "https://oldschool.runescape.wiki/w/Unpowered_orb")
        self.assertIsNone(serialize.wiki_url(None))


class ApiTest(unittest.TestCase):
    """End-to-end through FastAPI against a temporary database."""

    @classmethod
    def setUpClass(cls):
        import tempfile
        from pathlib import Path
        cls.tmp = tempfile.TemporaryDirectory()
        cls.patch = mock.patch.object(config, "DB_PATH", Path(cls.tmp.name) / "test.db")
        cls.patch.start()
        conn = db.connect()
        fetch = FakeFetch({"/mapping": load_fixture("mapping.json"),
                           "api.php": load_fixture("recipe_bucket.json")})
        mapping.refresh(conn, fetch)
        recipes.refresh(conn, fetch, Overrides())
        now = int(time.time())
        prices.refresh_latest(conn, FakeFetch({"/latest": {"data": {
            "1775": {"high": 100, "highTime": now, "low": 95, "lowTime": now},
            "567": {"high": 210, "highTime": now, "low": 200, "lowTime": now},
        }}}))
        hour = (now // 3600) * 3600
        for i in range(24):
            prices.store_hour(conn, {"timestamp": hour - i * 3600, "data": {
                "1775": {"avgHighPrice": 100, "highPriceVolume": 5000, "avgLowPrice": 95, "lowPriceVolume": 5000},
                "567": {"avgHighPrice": 210, "highPriceVolume": 5000, "avgLowPrice": 200, "lowPriceVolume": 5000},
            }})
        conn.close()
        cls.client = TestClient(create_app(run_scheduler=False))

    @classmethod
    def tearDownClass(cls):
        cls.patch.stop()
        cls.tmp.cleanup()

    def test_activities(self):
        body = self.client.get("/api/activities?mode=instant").json()
        orb = next(a for a in body["activities"] if a["name"] == "Unpowered orb" and a["type"] == "recipe")
        self.assertEqual(orb["profit"], 96)
        self.assertEqual(orb["skills"], [{"skill": "Crafting", "level": 46}])
        self.assertEqual(orb["risk"], "low")
        self.assertTrue(orb["liquid"])
        self.assertEqual(orb["wiki_url"], "https://oldschool.runescape.wiki/w/Unpowered_orb")

    def test_detail_fields(self):
        body = self.client.get("/api/activities").json()
        orb = next(a for a in body["activities"] if a["name"] == "Unpowered orb" and a["type"] == "recipe")
        self.assertEqual({c["limit"] for c in orb["caps"]}, {"speed", "buy_limit", "liquidity"})
        self.assertEqual(orb["assumptions"]["override_key"], "Unpowered orb")
        self.assertEqual(orb["day_profit"], 200 - 4 - 100)

    def test_history(self):
        body = self.client.get("/api/history/567?hours=12").json()
        self.assertEqual(len(body["points"]), 12)
        self.assertLess(body["points"][0]["ts"], body["points"][-1]["ts"])
        self.assertEqual(body["points"][0]["high_volume"], 5000)
        self.assertEqual(self.client.get("/api/history/424242").status_code, 404)

    def test_bad_mode(self):
        self.assertEqual(self.client.get("/api/activities?mode=greedy").status_code, 422)

    def test_status(self):
        body = self.client.get("/api/status").json()
        self.assertIsNotNone(body["refreshed"]["mapping"])
        self.assertEqual(body["snapshot_hours"]["day"], 24)

    def test_hiscores_not_found(self):
        with mock.patch.object(hiscores, "lookup", side_effect=hiscores.PlayerNotFound("x")):
            self.assertEqual(self.client.get("/api/hiscores?name=x").status_code, 404)

    def test_hiscores_name_length(self):
        self.assertEqual(self.client.get("/api/hiscores?name=thirteenchars").status_code, 422)


class SchedulerTest(unittest.TestCase):
    def test_failed_job_is_recorded_and_cleared(self):
        updates = []
        scheduler = Scheduler(on_update=updates.append)
        with mock.patch.object(db, "connect", return_value=db.connect(":memory:")):
            scheduler.run_job("boom", lambda conn: 1 / 0)
        self.assertIn("ZeroDivisionError", scheduler.errors["boom"])
        with mock.patch.object(db, "connect", return_value=db.connect(":memory:")):
            scheduler.run_job("boom", lambda conn: None)
        self.assertNotIn("boom", scheduler.errors)
        self.assertEqual(updates, ["boom"])

    def test_due(self):
        conn = db.connect(":memory:")
        scheduler = Scheduler(on_update=lambda _: None)
        latest = next(j for j in JOBS if j.name == "latest")
        self.assertTrue(scheduler.due(conn, latest))
        db.mark_refreshed(conn, "latest")
        self.assertFalse(scheduler.due(conn, latest))


if __name__ == "__main__":
    unittest.main()
