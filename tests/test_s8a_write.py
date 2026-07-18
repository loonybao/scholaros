"""S8a safe write layer: create/update applications, manual annotations,
ownership protection, stale-write rejection, and view refresh."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from compass.index import applications_data, rebuild_index
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


def test_create_application_from_opportunity(cfg, store):
    client, opp_id = _client(cfg, store)
    r = client.post(f"/api/opportunities/{opp_id}/applications")
    assert r.status_code == 200
    app_id = r.json()["id"]
    assert store.exists("application", app_id)
    assert store.load("application", app_id).manual.stage == "identified"
    # duplicate application is refused
    assert client.post(f"/api/opportunities/{opp_id}/applications").status_code == 409


def test_full_prepare_submit_flow(cfg, store):
    client, opp_id = _client(cfg, store)
    app_id = client.post(f"/api/opportunities/{opp_id}/applications").json()["id"]

    # identified -> preparing, add a checklist
    r = client.patch(f"/api/applications/{app_id}", json={
        "stage": "preparing",
        "materials": [{"name": "CV", "status": "todo"},
                      {"name": "Motivation letter", "status": "todo"}],
        "internal_due_date": "2026-08-01",
    })
    assert r.status_code == 200
    v1 = r.json()["updated_at"]

    # complete a checklist item
    r = client.patch(f"/api/applications/{app_id}", json={
        "expected_updated_at": v1,
        "materials": [{"name": "CV", "status": "final"},
                      {"name": "Motivation letter", "status": "final"}],
    })
    assert r.status_code == 200
    v2 = r.json()["updated_at"]

    # preparing -> submitted requires submitted_at + confirmation
    bad = client.patch(f"/api/applications/{app_id}", json={
        "expected_updated_at": v2, "stage": "submitted"})
    assert bad.status_code == 400  # missing submitted_at/confirmation

    r = client.patch(f"/api/applications/{app_id}", json={
        "expected_updated_at": v2, "stage": "submitted",
        "submitted_at": "2026-07-30", "confirm_submitted": True,
        "portal_reference": "REF-123",
        "documents_used": ["CV v2", "Motivation letter v1"]})
    assert r.status_code == 200

    app = store.load("application", app_id)
    assert app.manual.stage == "submitted"
    assert app.manual.submitted_at == date(2026, 7, 30)
    assert app.manual.portal_reference == "REF-123"
    assert app.manual.documents_used == ["CV v2", "Motivation letter v1"]
    assert app.change_history[-1].actor == "user"

    # reflected in the pipeline view
    data = applications_data(cfg)
    assert any(a["id"] == app_id for a in data["stages"]["submitted"])


def test_invalid_transition_rejected(cfg, store):
    client, opp_id = _client(cfg, store)
    app_id = client.post(f"/api/opportunities/{opp_id}/applications").json()["id"]
    # identified -> submitted is not a permitted forward transition
    r = client.patch(f"/api/applications/{app_id}", json={"stage": "submitted"})
    assert r.status_code == 422


def test_stale_write_rejected(cfg, store):
    client, opp_id = _client(cfg, store)
    app_id = client.post(f"/api/opportunities/{opp_id}/applications").json()["id"]
    r = client.patch(f"/api/applications/{app_id}", json={"next_step": "a"})
    stale = r.json()["updated_at"]
    client.patch(f"/api/applications/{app_id}", json={"next_step": "b"})  # bumps version
    r2 = client.patch(f"/api/applications/{app_id}",
                      json={"expected_updated_at": stale, "next_step": "c"})
    assert r2.status_code == 409


def test_ownership_official_ai_smuggling_rejected(cfg, store):
    client, opp_id = _client(cfg, store)
    # extra=forbid on the request models blocks official/ai/derived keys.
    for body in ({"title": "hacked"}, {"deadline": "2030-01-01"},
                 {"fit_overall": 100}, {"recommendation": "apply"}):
        r = client.patch(f"/api/opportunities/{opp_id}/manual", json=body)
        assert r.status_code == 422
    # official title is unchanged
    assert store.load("opportunity", opp_id).official.title.startswith("Doctoral")


def test_manual_user_status_write(cfg, store):
    client, opp_id = _client(cfg, store)
    r = client.patch(f"/api/opportunities/{opp_id}/manual",
                     json={"user_status": "future_target"})
    assert r.status_code == 200
    assert store.load("opportunity", opp_id).manual.user_status == "future_target"


def test_data_issue_creates_review_action_not_edit(cfg, store):
    client, opp_id = _client(cfg, store)
    before = store.load("opportunity", opp_id).official.deadline
    r = client.post("/api/data-issues", json={
        "opportunity_id": opp_id, "field": "deadline",
        "description": "deadline looks wrong"})
    assert r.status_code == 200
    act = store.load("action", r.json()["id"])
    assert act.system.action_type == "admin"
    assert "deadline" in act.manual.title
    # official fact NOT edited in place
    assert store.load("opportunity", opp_id).official.deadline == before


def test_no_op_update_no_history_growth(cfg, store):
    client, opp_id = _client(cfg, store)
    app_id = client.post(f"/api/opportunities/{opp_id}/applications").json()["id"]
    n = len(store.load("application", app_id).change_history)
    # same notes value twice -> the second is a no-op
    client.patch(f"/api/applications/{app_id}", json={"notes": "hello"})
    mid = len(store.load("application", app_id).change_history)
    client.patch(f"/api/applications/{app_id}", json={"notes": "hello"})
    end = len(store.load("application", app_id).change_history)
    assert mid == n + 1 and end == mid  # no-op added no history


def test_read_routes_still_work(cfg, store):
    client, opp_id = _client(cfg, store)
    for path in ("/api/dashboard", "/api/skills", "/api/opportunities",
                 "/api/targets", "/api/applications", "/api/signals",
                 "/api/researchers", "/api/health", f"/api/opportunities/{opp_id}"):
        assert client.get(path).status_code == 200
