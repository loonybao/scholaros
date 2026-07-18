"""S8a.1 contract tests: audited submission correction, the closed
submitted->preparing backdoor, the readable activity history, and the
incremental write path (ordinary writes must not trigger a full rebuild/export,
and must produce state identical to a full rebuild)."""
import pytest
from fastapi.testclient import TestClient

from compass import views
from compass.export_vault import VaultExporter
from compass.index import applications_data, connect, rebuild_index
from compass.rules import recompute_derived
from compass.web import create_app
from conftest import TODAY, make_opportunity, make_organisation


def _client(cfg, store):
    store.save(make_organisation(), actor="manual")
    opp = make_opportunity()
    opp.derived = recompute_derived(opp, cfg.constraints, TODAY)
    store.save(opp, actor="manual")
    rebuild_index(cfg, store)
    return TestClient(create_app(cfg)), opp.id


def _submit(client, opp_id):
    app_id = client.post(f"/api/opportunities/{opp_id}/applications").json()["id"]
    v = client.patch(f"/api/applications/{app_id}", json={"stage": "preparing"}).json()["updated_at"]
    r = client.patch(f"/api/applications/{app_id}", json={
        "expected_updated_at": v, "stage": "submitted",
        "submitted_at": "2026-07-30", "confirm_submitted": True,
        "portal_reference": "REF-1", "documents_used": ["CV v2"]})
    return app_id, r.json()["updated_at"]


# ---------------------------------------------------------- A: correction #

def test_generic_patch_cannot_reopen_submitted(cfg, store):
    client, opp_id = _client(cfg, store)
    app_id, v = _submit(client, opp_id)
    # the normal PATCH route must refuse submitted -> preparing (no backdoor)
    r = client.patch(f"/api/applications/{app_id}",
                     json={"expected_updated_at": v, "stage": "preparing"})
    assert r.status_code == 422
    assert store.load("application", app_id).manual.stage == "submitted"


def test_correction_reopens_with_reason_and_clears_fields(cfg, store):
    client, opp_id = _client(cfg, store)
    app_id, v = _submit(client, opp_id)
    r = client.post(f"/api/applications/{app_id}/correct-submission", json={
        "expected_updated_at": v,
        "correction_reason": "Testing the workflow; no real submission was made.",
        "confirm": True})
    assert r.status_code == 200
    m = store.load("application", app_id).manual
    assert m.stage == "preparing"
    assert m.submitted_at is None and m.portal_reference is None
    assert m.documents_used == []


def test_correction_requires_reason_and_confirmation(cfg, store):
    client, opp_id = _client(cfg, store)
    app_id, v = _submit(client, opp_id)
    assert client.post(f"/api/applications/{app_id}/correct-submission",
                       json={"expected_updated_at": v, "correction_reason": "", "confirm": True}
                       ).status_code == 400
    assert client.post(f"/api/applications/{app_id}/correct-submission",
                       json={"expected_updated_at": v, "correction_reason": "x", "confirm": False}
                       ).status_code == 400
    assert store.load("application", app_id).manual.stage == "submitted"


def test_correction_only_on_submitted(cfg, store):
    client, opp_id = _client(cfg, store)
    app_id = client.post(f"/api/opportunities/{opp_id}/applications").json()["id"]
    r = client.post(f"/api/applications/{app_id}/correct-submission",
                    json={"correction_reason": "x", "confirm": True})
    assert r.status_code == 422  # not currently submitted


def test_correction_rejects_stale(cfg, store):
    client, opp_id = _client(cfg, store)
    app_id, v = _submit(client, opp_id)
    client.patch(f"/api/applications/{app_id}", json={"next_step": "bumps version"})
    r = client.post(f"/api/applications/{app_id}/correct-submission",
                    json={"expected_updated_at": v, "correction_reason": "x", "confirm": True})
    assert r.status_code == 409


def test_correction_preserves_audit_history(cfg, store):
    client, opp_id = _client(cfg, store)
    app_id, v = _submit(client, opp_id)
    client.post(f"/api/applications/{app_id}/correct-submission", json={
        "expected_updated_at": v, "correction_reason": "mistake", "confirm": True})
    events = [e.event for e in store.load("application", app_id).manual.events]
    # the original submission event is NOT erased; the correction is recorded
    assert "submitted" in events and "corrected" in events
    corrected = [e for e in store.load("application", app_id).manual.events
                 if e.event == "corrected"][0]
    assert "mistake" in corrected.note and "was submitted" in corrected.note


# ------------------------------------------------------ B: activity history #

def test_activity_history_surfaced_in_pipeline(cfg, store):
    client, opp_id = _client(cfg, store)
    app_id, _ = _submit(client, opp_id)
    data = applications_data(cfg)
    app = next(a for a in data["stages"]["submitted"] if a["id"] == app_id)
    kinds = {e["event"] for e in app["events"]}
    assert {"created", "preparing", "submitted"} <= kinds


# ---------------------------------------- D/E: incremental, not full rebuild #

def test_ordinary_write_does_not_full_rebuild_or_export_all(cfg, store, monkeypatch):
    client, opp_id = _client(cfg, store)
    app_id = client.post(f"/api/opportunities/{opp_id}/applications").json()["id"]

    def _boom(*a, **k):
        raise AssertionError("ordinary write triggered a FULL rebuild/export")

    monkeypatch.setattr(views, "rebuild_index", _boom)
    monkeypatch.setattr(VaultExporter, "export_all", _boom)

    # a checklist update must go through the incremental path only
    r = client.patch(f"/api/applications/{app_id}",
                     json={"materials": [{"name": "CV", "status": "final"}]})
    assert r.status_code == 200
    assert r.json().get("warning") is None


def test_incremental_row_matches_full_rebuild(cfg, store):
    client, opp_id = _client(cfg, store)
    app_id, _ = _submit(client, opp_id)

    conn = connect(cfg)
    incremental = dict(conn.execute(
        "SELECT * FROM applications WHERE id=?", (app_id,)).fetchone())
    conn.close()

    rebuild_index(cfg, store)          # authoritative full rebuild
    conn = connect(cfg)
    full = dict(conn.execute(
        "SELECT * FROM applications WHERE id=?", (app_id,)).fetchone())
    conn.close()
    assert incremental == full


def test_get_routes_never_rebuild_or_export(cfg, store, monkeypatch):
    client, opp_id = _client(cfg, store)
    monkeypatch.setattr(views, "rebuild_index",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("GET rebuilt index")))
    monkeypatch.setattr(VaultExporter, "export_all",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("GET exported vault")))
    for path in ("/api/dashboard", "/api/skills", "/api/opportunities",
                 "/api/targets", "/api/applications", "/api/signals",
                 "/api/health", f"/api/opportunities/{opp_id}"):
        assert client.get(path).status_code == 200


# ------------------------------------------------- I: reconcile on failure #

def test_partial_refresh_keeps_canonical_and_warns(cfg, store, monkeypatch):
    client, opp_id = _client(cfg, store)
    app_id = client.post(f"/api/opportunities/{opp_id}/applications").json()["id"]

    # simulate the vault export failing AFTER canonical is saved
    monkeypatch.setattr(VaultExporter, "export_application",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk full")))
    r = client.patch(f"/api/applications/{app_id}", json={"stage": "preparing"})
    assert r.status_code == 200
    assert r.json().get("warning")                       # user is warned
    assert store.load("application", app_id).manual.stage == "preparing"  # canonical kept
    assert (cfg.paths.status / "needs_reconcile.json").exists()           # marked for reconcile
