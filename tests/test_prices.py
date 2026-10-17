import time
import unittest

from backend.ingest import mapping, prices
from tests.helpers import FakeFetch, load_fixture, memory_db

HOUR = 3600


def hour_payload(ts, volume=10, price=100):
    return {"timestamp": ts, "data": {
        "1775": {"avgHighPrice": price + 2, "highPriceVolume": volume,
                 "avgLowPrice": price, "lowPriceVolume": volume},
        "99999": {"avgHighPrice": 1, "highPriceVolume": 1, "avgLowPrice": 1, "lowPriceVolume": 1},
    }}


def setup():
    conn = memory_db()
    mapping.refresh(conn, FakeFetch({"/mapping": load_fixture("mapping.json")}))
    return conn


class LatestTest(unittest.TestCase):
    def test_stores_known_items_only(self):
        conn = setup()
        fetch = FakeFetch({"/latest": {"data": {
            "1775": {"high": 150, "highTime": 1, "low": 140, "lowTime": 2},
            "99999": {"high": 1, "highTime": 1, "low": 1, "lowTime": 1},
        }}})
        self.assertEqual(prices.refresh_latest(conn, fetch), 1)
        row = conn.execute("SELECT * FROM latest_prices WHERE item_id = 1775").fetchone()
        self.assertEqual((row["high"], row["low"]), (150, 140))

    def test_missing_side_is_null(self):
        conn = setup()
        prices.refresh_latest(conn, FakeFetch({"/latest": {"data": {"567": {"high": 90, "highTime": 1}}}}))
        row = conn.execute("SELECT * FROM latest_prices WHERE item_id = 567").fetchone()
        self.assertIsNone(row["low"])


class HourlyTest(unittest.TestCase):
    def setUp(self):
        self.now = (int(time.time()) // HOUR) * HOUR
        self.conn = setup()

    def test_backfill_fetches_only_missing_hours(self):
        prices.store_hour(self.conn, hour_payload(self.now - 2 * HOUR))
        fetch = FakeFetch({"/1h": lambda p: hour_payload(p["timestamp"] if p else self.now)})
        fetched = prices.backfill(self.conn, 4, fetch, sleep=lambda _: None)
        self.assertEqual(fetched, 2)  # now-1h and now-3h; now came from the first call
        self.assertEqual(prices.snapshot_coverage(self.conn, 24), 4)

    def test_daily_volume_covers_last_24_hours_only(self):
        for i in range(30):
            prices.store_hour(self.conn, hour_payload(self.now - i * HOUR, volume=5))
        row = self.conn.execute("SELECT * FROM daily_volume WHERE item_id = 1775").fetchone()
        self.assertEqual(row["volume"], 24 * 10)
        self.assertEqual(row["high_volume"], 24 * 5)

    def test_prune_drops_old_snapshots(self):
        prices.store_hour(self.conn, hour_payload(self.now - 40 * 86400))
        prices.store_hour(self.conn, hour_payload(self.now))
        prices.prune(self.conn)
        self.assertEqual(prices.snapshot_coverage(self.conn, 24 * 60), 1)


if __name__ == "__main__":
    unittest.main()
