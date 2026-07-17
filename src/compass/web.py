"""Read-only web dashboard (S2).

Binds 127.0.0.1 only. No write endpoints in S2 — decision finalization and
application editing arrive in S4/S6. All data flows canonical JSON -> SQLite
index -> API; nothing is hard-coded in the frontend.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import Config
from .index import dashboard_data, health_data, rebuild_index
from .store import Store

WEBUI_DIR = Path(__file__).parent / "webui"


def create_app(cfg: Config) -> FastAPI:
    app = FastAPI(title="Research Compass", docs_url=None, redoc_url=None)

    @app.get("/api/dashboard")
    def api_dashboard() -> dict:
        return dashboard_data(cfg, date.today())

    @app.get("/api/health")
    def api_health() -> dict:
        return health_data(cfg)

    @app.get("/")
    def root() -> FileResponse:
        return FileResponse(WEBUI_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=WEBUI_DIR), name="static")
    return app


def serve(cfg: Config, port: int = 8000, host: str = "127.0.0.1") -> None:
    import uvicorn

    # Rebuild the index at startup so the dashboard always reflects canonical.
    store = Store(cfg.paths.canonical, cfg.paths.lock_file)
    rebuild_index(cfg, store)
    uvicorn.run(create_app(cfg), host=host, port=port, log_level="warning")
