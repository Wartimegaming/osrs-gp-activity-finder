"""FastAPI app: JSON API under /api and the built React UI at /."""

import asyncio
import contextlib
import json
import threading
import time
from pathlib import Path

from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from backend import config, db
from backend.api import hiscores, serialize
from backend.api.scheduler import JOBS, Scheduler
from backend.engine import history, market as market_mod, merch
from backend.engine.ranking import evaluate_all
from backend.engine.settings import PriceMode, Settings
from backend.ingest import icons, prices

FRONTEND_DIST = config.ROOT / "frontend" / "dist"
SELL_WINDOWS = {1, 4, 12, 24}  # hours; the choices offered in the UI


class MarkUpdate(BaseModel):
    key: str
    mark: Literal["favourite", "hidden"] | None  # None clears the mark


class ResultCache:
    """Evaluated activities per price mode as encoded JSON, rebuilt after any data refresh."""

    def __init__(self):
        self._lock = threading.Lock()
        self._version = 0
        self._entries: dict[object, tuple[int, bytes]] = {}

    def invalidate(self, _job: str = "") -> None:
        with self._lock:
            self._version += 1

    def get(self, mode: PriceMode, sell_hours: int = 1) -> bytes:
        return self._cached((mode, sell_hours), lambda: self._build(mode, sell_hours))

    def merch(self) -> bytes:
        return self._cached("merch", self._build_merch)

    def _cached(self, key, build) -> bytes:
        with self._lock:
            version = self._version
            entry = self._entries.get(key)
            if entry and entry[0] == version:
                return entry[1]
        payload = build()
        with self._lock:
            self._entries[key] = (version, payload)
        return payload

    @staticmethod
    def _build_merch() -> bytes:
        conn = db.connect()
        try:
            now = int(time.time())
            market = market_mod.load(conn, now)
            _, series = history.load_series(conn)
        finally:
            conn.close()
        rows = [c.to_dict() for c in merch.candidates(market, series, Settings())]
        return json.dumps({"generated_at": now, "count": len(rows), "items": rows},
                          separators=(",", ":"), allow_nan=False).encode()

    @staticmethod
    def _build(mode: PriceMode, sell_hours: int) -> bytes:
        conn = db.connect()
        try:
            now = int(time.time())
            settings = Settings(price_mode=mode, sell_window_hours=sell_hours)
            market = market_mod.load(conn, now)
            results = evaluate_all(conn, settings, market=market)
        finally:
            conn.close()
        rows = [serialize.result(r, market, settings) for r in results if r.profit is not None and r.profit > 0]
        payload = {"mode": mode, "sell_hours": sell_hours, "generated_at": now, "count": len(rows), "activities": rows}
        # Encoded once per data refresh; several MB, so re-encoding per request would dominate.
        return json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()


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
    async def activities(mode: PriceMode = PriceMode.INSTANT, sell_hours: int = 1):
        if sell_hours not in SELL_WINDOWS:
            raise HTTPException(422, f"sell_hours must be one of {sorted(SELL_WINDOWS)}")
        scheduler.touch()
        return Response(await asyncio.to_thread(cache.get, mode, sell_hours), media_type="application/json")

    @app.get("/api/merch")
    async def merchanting():
        """Margin-flip candidates with buy/sell prices, volumes and signals."""
        scheduler.touch()
        return Response(await asyncio.to_thread(cache.merch), media_type="application/json")

    @app.get("/api/status")
    def status():
        scheduler.touch()
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
                "viewer_active": scheduler.viewer_active,
                "icons_missing": len(icons.missing(conn)),
                "errors": scheduler.errors,
                "snapshot_hours": {
                    "day": prices.snapshot_coverage(conn, 24),
                    "week": prices.snapshot_coverage(conn, 168),
                },
            }
        finally:
            conn.close()

    @app.get("/api/history/{item_id}")
    def history(item_id: int, hours: int = Query(168, ge=1, le=24 * 30)):
        """Hourly average prices and volumes for one item, oldest first."""
        conn = db.connect()
        try:
            if not conn.execute("SELECT 1 FROM items WHERE id = ?", (item_id,)).fetchone():
                raise HTTPException(404, f"Unknown item {item_id}")
            rows = conn.execute(
                "SELECT ts, avg_high, avg_low, high_volume, low_volume FROM hourly_prices "
                "WHERE item_id = ? AND ts > (SELECT MAX(ts) FROM hourly_prices) - ? ORDER BY ts",
                (item_id, hours * 3600),
            ).fetchall()
            newest = conn.execute("SELECT MAX(ts) FROM hourly_prices").fetchone()[0]
        finally:
            conn.close()
        return {"item_id": item_id, "hours": hours, "newest": newest, "points": [dict(r) for r in rows]}

    @app.get("/api/marks")
    def marks():
        conn = db.connect()
        try:
            return {r["activity_key"]: r["mark"] for r in conn.execute("SELECT * FROM user_marks")}
        finally:
            conn.close()

    @app.put("/api/marks")
    def set_mark(update: MarkUpdate):
        conn = db.connect()
        try:
            with conn:
                if update.mark is None:
                    conn.execute("DELETE FROM user_marks WHERE activity_key = ?", (update.key,))
                else:
                    conn.execute(
                        "INSERT INTO user_marks (activity_key, mark, updated_at) VALUES (?, ?, ?) "
                        "ON CONFLICT(activity_key) DO UPDATE SET mark = excluded.mark, updated_at = excluded.updated_at",
                        (update.key, update.mark, int(time.time())),
                    )
            return {"key": update.key, "mark": update.mark}
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

    @app.get("/icons/{item_id}.png")
    def icon(item_id: int):
        conn = db.connect()
        try:
            row = conn.execute("SELECT icon FROM items WHERE id = ?", (item_id,)).fetchone()
        finally:
            conn.close()
        path = icons.path_for(row["icon"]) if row and row["icon"] else None
        if path is None or not path.is_file():
            # Not downloaded yet; the background icon job fetches it. Never proxy to the wiki here.
            raise HTTPException(404, "Icon not cached yet")
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "public, max-age=604800"})

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
