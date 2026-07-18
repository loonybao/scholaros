"""Read-only web dashboard (S2).

Binds 127.0.0.1 only. No write endpoints in S2 — decision finalization and
application editing arrive in S4/S6. All data flows canonical JSON -> SQLite
index -> API; nothing is hard-coded in the frontend.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import Config
from .index import (
    applications_data,
    browse_opportunities,
    dashboard_data,
    health_data,
    opportunity_detail,
    people_list,
    rebuild_index,
    signals_feed,
    skills_radar,
    watchlist_data,
)
from .store import Store
from . import webwrite as w

WEBUI_DIR = Path(__file__).parent / "webui"

BROWSE_FILTERS = (
    "org_id", "lab_org_id", "fit_type", "recommendation", "eligibility_gate",
    "future_group_value", "position_type", "status", "timing_assessment", "q",
    "rejection_reason", "skill", "deadline_status", "scope",
)


def create_app(cfg: Config) -> FastAPI:
    app = FastAPI(title="Research Compass", docs_url=None, redoc_url=None)
    store = Store(cfg.paths.canonical, cfg.paths.lock_file)

    def _write(fn, *args):
        try:
            return fn(cfg, store, *args)
        except w.WriteError as e:
            raise HTTPException(status_code=e.status, detail=str(e))

    @app.get("/api/dashboard")
    def api_dashboard() -> dict:
        return dashboard_data(cfg, date.today())

    @app.get("/api/health")
    def api_health() -> dict:
        return health_data(cfg)

    @app.get("/api/skills")
    def api_skills() -> dict:
        return skills_radar(cfg)

    @app.get("/api/opportunities")
    def api_opportunities(request: Request) -> dict:
        filters = {
            k: request.query_params.get(k)
            for k in BROWSE_FILTERS if request.query_params.get(k)
        }
        rows = browse_opportunities(cfg, filters)
        return {"count": len(rows), "filters": filters, "opportunities": rows}

    @app.get("/api/targets")
    def api_targets() -> dict:
        return {"targets": watchlist_data(cfg)}

    @app.get("/api/signals")
    def api_signals() -> dict:
        return {"signals": signals_feed(cfg)}

    @app.get("/api/researchers")
    def api_researchers() -> dict:
        return {"researchers": people_list(cfg)}

    @app.get("/api/opportunities/{opp_id}")
    def api_opportunity_detail(opp_id: str) -> dict:
        detail = opportunity_detail(cfg, store, opp_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="unknown opportunity")
        return detail

    # ---- write endpoints (manual-layer / Application / Action only) ----

    @app.post("/api/opportunities/{opp_id}/applications")
    def api_create_application(opp_id: str) -> dict:
        return _write(w.create_application, opp_id)

    @app.patch("/api/opportunities/{opp_id}/manual")
    def api_patch_opp_manual(opp_id: str, patch: w.OppManualPatch) -> dict:
        return _write(w.patch_opportunity_manual, opp_id, patch)

    @app.patch("/api/applications/{app_id}")
    def api_patch_application(app_id: str, patch: w.AppPatch) -> dict:
        return _write(w.patch_application, app_id, patch)

    @app.post("/api/applications/{app_id}/correct-submission")
    def api_correct_submission(app_id: str, req: w.SubmissionCorrection) -> dict:
        return _write(w.correct_submission, app_id, req)

    @app.post("/api/actions")
    def api_create_action(req: w.ActionCreate) -> dict:
        return _write(w.create_action, req)

    @app.put("/api/skills/{skill_id}/progress")
    def api_set_skill_progress(skill_id: str, patch: w.SkillProgressPatch) -> dict:
        return _write(w.set_skill_progress, skill_id, patch)

    @app.post("/api/data-issues")
    def api_data_issue(req: w.DataIssue) -> dict:
        return _write(w.report_data_issue, req)

    @app.get("/api/applications")
    def api_applications() -> dict:
        return applications_data(cfg)

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
