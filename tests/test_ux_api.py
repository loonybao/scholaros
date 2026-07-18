"""API contract for the UX shell: dashboard meaningful_changes + graduation
horizon shaping, /api/researchers, and read-only guarantees."""
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from compass.index import rebuild_index
from compass.models import (
    Person, PersonOfficial, Signal, SignalOfficial,
)
from compass.rules import recompute_derived
from compass.web import create_app
from conftest import TODAY, make_opportunity, make_organisation

NOW = datetime(2026, 7, 17, tzinfo=timezone.utc)


def _seed(cfg, store):
    store.save(make_organisation(), actor="manual")
    store.save(Person(id="per_x", official=PersonOfficial(
        name="Test PI", org_id="org_test_university", title="Professor")), actor="manual")
    store.save(Signal(id="sig_x", official=SignalOfficial(
        signal_type="lab_news", title="New funded project", org_id="org_test_university",
        retrieved_at=NOW)), actor="manual")
    opp = make_opportunity()
    opp.derived = recompute_derived(opp, cfg.constraints, TODAY)
    store.save(opp, actor="manual")
    rebuild_index(cfg, store)
    return TestClient(create_app(cfg))


def test_dashboard_has_meaningful_changes_and_horizon(cfg, store):
    client = _seed(cfg, store)
    data = client.get("/api/dashboard").json()
    assert "meaningful_changes" in data
    assert any(c["kind"] == "signal" for c in data["meaningful_changes"])
    assert "graduation_horizon" in data  # None here (no expected completion in cfg)


def test_researchers_endpoint(cfg, store):
    client = _seed(cfg, store)
    data = client.get("/api/researchers").json()
    assert [p["id"] for p in data["researchers"]] == ["per_x"]
    assert data["researchers"][0]["org_name"] == "Test University"


def test_new_read_only_endpoints_have_no_writes(cfg, store):
    client = _seed(cfg, store)
    for path in ("/api/researchers",):
        assert client.get(path).status_code == 200
        assert client.post(path).status_code in (404, 405)
