"""FastAPI app: JSON API under /api and the built React UI at /."""

import asyncio
import contextlib
import threading
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend import config, db
from backend.api import hiscores, serialize
from backend.api.scheduler import JOBS, Scheduler
from backend.engine import market as market_mod
from backend.engine.ranking import evaluate_all
from backend.engine.settings import PriceMode, Settings
from backend.ingest import prices

FRONTEND_DIST = config.ROOT / "frontend" / "dist"


class ResultCache:
    """Evaluated activities per price mode, rebuilt after any data refresh."""

    def __init__(self):
        self._lock = threading.Lock()
        self._version = 0
        self._entries: dict[PriceMode, tuple[int, dict]] = {}

    def invalidate(self, _job: str = "") -> None:
        with self._lock:
            self._version += 1

    def get(self, mode: PriceMode) -> dict:
        with self._lock:
            version = self._version
            entry = self._entries.get(mode)
            if entry and entry[0] == version:
                return entry[1]
        payload = self._build(mode)
        with self._lock:
            self._entries[mode] = (version, payload)
        return payload

    @staticmethod
    def _build(mode: PriceMode) -> dict:
        conn = db.connect()
        try:
            now = int(time.time())
            market = market_mod.load(conn, now)
            results = evaluate_all(conn, Settings(price_mode=mode), market=market)
        finally:
            conn.close()
        rows = [serialize.result(r, market) for r in results if r.profit is not None and r.profit > 0]
        return {"mode": mode, "generated_at": now, "count": len(rows), "activities": rows}


def create_app(run_scheduler: bool = True) -> FastAPI:
    cache = ResultCache()
    scheduler = Scheduler(on_update=cache.invalidate)

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        task = asyncio.create_task(scheduler.loop()) if run_scheduler else None
        yield
        if task:
            task.cancel()

    app = FastAPI(title="OSRS GP Activity Finder", lifespan=lifespan)
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    @app.get("/api/activities")
    async def activities(mode: PriceMode = PriceMode.INSTANT):
        return await asyncio.to_thread(cache.get, mode)

    @app.get("/api/status")
    def status():
        conn = db.connect()
        try:
            refreshed = {
                job: int(value) if (value := db.get_meta(conn, f"refreshed:{job}")) else None
                for job in [j.name for j in JOBS]
            }
            return {
                "now": int(time.time()),
                "refreshed": refreshed,
                "intervals": {j.name: j.interval for j in JOBS},
                "running": sorted(scheduler.running),
                "errors": scheduler.errors,
                "snapshot_hours": {
                    "day": prices.snapshot_coverage(conn, 24),
                    "week": prices.snapshot_coverage(conn, 168),
                },
            }
        finally:
            conn.close()

    @app.post("/api/refresh")
    async def refresh():
        job = next(j for j in JOBS if j.name == "latest")
        await asyncio.to_thread(scheduler.run_job, job.name, job.run)
        return {"ok": "latest" not in scheduler.errors, "error": scheduler.errors.get("latest")}

    @app.get("/api/hiscores")
    async def player(name: str = Query(min_length=1, max_length=12)):
        try:
            return await asyncio.to_thread(hiscores.lookup, name)
        except hiscores.PlayerNotFound:
            raise HTTPException(404, f"No hiscores entry for '{name}'")
        except Exception as exc:
            raise HTTPException(502, f"Hiscores lookup failed: {exc}")

    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    if not FRONTEND_DIST.exists():
        @app.get("/")
        def no_frontend():
            return {"message": "Frontend not built. Run `npm run build` in frontend/, "
                               "or use the Vite dev server on port 5173."}
        return

    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        file = (FRONTEND_DIST / path).resolve()
        if path and file.is_file() and file.is_relative_to(FRONTEND_DIST.resolve()):
            return FileResponse(file)
        return FileResponse(FRONTEND_DIST / "index.html")
