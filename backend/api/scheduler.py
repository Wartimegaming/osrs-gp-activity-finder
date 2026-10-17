"""Background refresh jobs. Each job opens its own SQLite connection and runs in a thread.

Jobs run when their data is older than their interval, so restarting the server doesn't
refetch everything. A failed job is logged and retried on the next tick.

To keep traffic to the wiki down: live prices are only polled while someone is using the UI,
hourly snapshots are fetched once per published hour, and slow jobs (history backfill, icon
downloads) run in their own thread with a pause between requests.
"""

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from backend import db
from backend.ingest import icons, mapping, prices, recipes, sets, shops

log = logging.getLogger("scheduler")

TICK_SECONDS = 15
BACKFILL_HOURS = 168
ACTIVE_SECONDS = 10 * 60  # the UI counts as in use for this long after its last request
HOURLY_PUBLISH_DELAY = 120  # the wiki publishes each hour's averages shortly after it ends


@dataclass
class Job:
    name: str
    interval: int  # seconds
    run: Callable
    background: bool = False  # slow job: run detached so other jobs keep going
    needs_viewer: bool = False  # only worth fetching while someone is looking


def hourly_due(conn, now: float) -> bool:
    """A new /1h snapshot exists once the previous full hour has been published."""
    newest = conn.execute("SELECT MAX(ts) FROM hourly_prices").fetchone()[0]
    published = (int(now - HOURLY_PUBLISH_DELAY) // 3600) * 3600 - 3600
    return newest is None or published > newest


JOBS = [
    Job("mapping", 24 * 3600, mapping.refresh),
    Job("recipes", 7 * 24 * 3600, recipes.refresh),
    Job("sets", 7 * 24 * 3600, sets.refresh),
    Job("shops", 7 * 24 * 3600, shops.refresh),
    Job("latest", 60, prices.refresh_latest, needs_viewer=True),
    Job("hourly", 3600, prices.refresh_hourly),
    Job("icons", 24 * 3600, lambda conn: icons.download(conn), background=True),
]


class Scheduler:
    def __init__(self, on_update: Callable[[str], None]):
        self.on_update = on_update  # called with the job name after new data lands
        self.running: set[str] = set()
        self.errors: dict[str, str] = {}
        self._lock = threading.Lock()
        self.last_viewed = 0.0

    def touch(self) -> None:
        """Called by API requests from the UI."""
        self.last_viewed = time.time()

    @property
    def viewer_active(self) -> bool:
        return time.time() - self.last_viewed < ACTIVE_SECONDS

    def due(self, conn, job: Job) -> bool:
        if job.needs_viewer and not self.viewer_active:
            return False
        if job.name == "hourly":
            return hourly_due(conn, time.time())
        last = db.get_meta(conn, f"refreshed:{job.name}")
        return last is None or time.time() - int(last) >= job.interval

    def run_job(self, name: str, fn: Callable[[object], object]) -> None:
        with self._lock:
            if name in self.running:
                return
            self.running.add(name)
        conn = db.connect()
        try:
            started = time.monotonic()
            fn(conn)
            self.errors.pop(name, None)
            log.info("%s refreshed in %.1fs", name, time.monotonic() - started)
            self.on_update(name)
        except Exception as exc:  # keep the loop alive; surface the error in /api/status
            self.errors[name] = f"{type(exc).__name__}: {exc}"
            log.exception("%s failed", name)
        finally:
            conn.close()
            with self._lock:
                self.running.discard(name)

    def start_background(self, name: str, fn: Callable[[object], object]) -> None:
        if name not in self.running:  # run_job also guards this; skip the thread entirely
            threading.Thread(target=self.run_job, args=(name, fn), daemon=True).start()

    async def loop(self) -> None:
        backfill_checked = False
        while True:
            conn = db.connect()
            try:
                due = [job for job in JOBS if self.due(conn, job)]
                needs_backfill = not backfill_checked and prices.snapshot_coverage(conn, BACKFILL_HOURS) < BACKFILL_HOURS
            finally:
                conn.close()
            # In list order: mapping must land before anything that matches item ids.
            for job in due:
                if job.background:
                    self.start_background(job.name, job.run)
                else:
                    await asyncio.to_thread(self.run_job, job.name, job.run)
            if needs_backfill:
                # Slow (one request per second); detached so live prices keep updating.
                self.start_background("backfill", lambda conn: prices.backfill(conn, BACKFILL_HOURS))
            backfill_checked = True
            await asyncio.sleep(TICK_SECONDS)
