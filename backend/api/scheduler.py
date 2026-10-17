"""Background refresh jobs. Each job opens its own SQLite connection and runs in a thread.

Jobs run when their data is older than their interval, so restarting the server doesn't
refetch everything. A failed job is logged and retried on the next tick.
"""

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from backend import db
from backend.ingest import mapping, prices, recipes, sets, shops

log = logging.getLogger("scheduler")

TICK_SECONDS = 15
BACKFILL_HOURS = 168


@dataclass
class Job:
    name: str
    interval: int  # seconds
    run: Callable


JOBS = [
    Job("mapping", 24 * 3600, mapping.refresh),
    Job("recipes", 7 * 24 * 3600, recipes.refresh),
    Job("sets", 7 * 24 * 3600, sets.refresh),
    Job("shops", 7 * 24 * 3600, shops.refresh),
    Job("latest", 60, prices.refresh_latest),
    Job("hourly", 15 * 60, prices.refresh_hourly),
]


class Scheduler:
    def __init__(self, on_update: Callable[[str], None]):
        self.on_update = on_update  # called with the job name after new data lands
        self.running: set[str] = set()
        self.errors: dict[str, str] = {}
        self._lock = threading.Lock()

    def due(self, conn, job: Job) -> bool:
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

    async def loop(self) -> None:
        backfill_checked = False
        while True:
            conn = db.connect()
            try:
                due = [job for job in JOBS if self.due(conn, job)]
                needs_backfill = not backfill_checked and prices.snapshot_coverage(conn, BACKFILL_HOURS) < BACKFILL_HOURS
            finally:
                conn.close()
            # Mapping must land before anything that matches item ids.
            for job in due:
                await asyncio.to_thread(self.run_job, job.name, job.run)
            if needs_backfill:
                backfill_checked = True
                # Slow (one request per second); run detached so live prices keep updating.
                threading.Thread(
                    target=self.run_job,
                    args=("backfill", lambda conn: prices.backfill(conn, BACKFILL_HOURS)),
                    daemon=True,
                ).start()
            backfill_checked = True
            await asyncio.sleep(TICK_SECONDS)
