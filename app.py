import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from server import db, store
from server.routes.api import router as api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Open the Lakebase pool + ensure the write-back table exists. Do NOT crash
    # the whole app if Lakebase is briefly unreachable at boot; the pool also
    # reconnects lazily on first query. Any error is captured for /api/debug.
    try:
        db.open_pool()
        store.init_store()
    except Exception as e:  # noqa: BLE001
        import traceback
        app.state.startup_error = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
    yield
    db.close_pool()


app = FastAPI(title="Care Manager Worklist", lifespan=lifespan)
app.include_router(api_router, prefix="/api")

_FRONTEND = os.path.realpath(os.path.join(os.path.dirname(__file__), "frontend", "dist"))

if os.path.exists(_FRONTEND):
    app.mount("/assets", StaticFiles(directory=os.path.join(_FRONTEND, "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        if full_path.startswith("api/"):
            raise FileNotFoundError
        index = os.path.join(_FRONTEND, "index.html")
        # Resolve and confirm the requested path stays inside the frontend dir
        # (prevents path traversal like ../../etc/passwd); otherwise serve the SPA shell.
        if full_path and ".." not in full_path.split("/"):
            candidate = os.path.realpath(os.path.join(_FRONTEND, full_path))
            if (candidate == _FRONTEND or candidate.startswith(_FRONTEND + os.sep)) and os.path.isfile(candidate):
                return FileResponse(candidate)
        # index.html must never be cached, or mobile webviews keep serving a stale
        # bundle after a redeploy (hashed /assets files are safe to cache).
        return FileResponse(index, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
