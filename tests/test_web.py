from fastapi.testclient import TestClient

from compass.index import rebuild_index
from compass.rules import recompute_derived
from compass.web import create_app
from conftest import TODAY, make_opportunity, make_organisation


def _client(cfg, store):
    store.save(make_organisation(), actor="manual")
    opp = make_opportunity()
    opp.derived = recompute_derived(opp, cfg.constraints, TODAY)
    store.save(opp, actor="manual")
    rebuild_index(cfg, store)
    return TestClient(create_app(cfg))


def test_api_dashboard(cfg, store):
    client = _client(cfg, store)
    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    data = resp.json()
    assert {"action_required", "open_opportunities", "upcoming_deadlines",
            "review_queue", "meta"} <= set(data)
    ids = [r["id"] for r in data["open_opportunities"]]
    assert "opp_test" in ids


def test_api_health(cfg, store):
    client = _client(cfg, store)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["entity_counts"]["opportunity"] == 1
    assert data["llm_configured"] is False


def test_root_serves_html(cfg, store):
    client = _client(cfg, store)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Research Compass" in resp.text
    assert "app.js" in resp.text


def test_dashboard_is_read_only(cfg, store):
    """S2 contract: no write endpoints exist."""
    client = _client(cfg, store)
    for method, path in [
        ("post", "/api/dashboard"),
        ("post", "/api/opportunities"),
        ("post", "/api/decisions/dec_x/finalize"),
        ("put", "/api/opportunities/opp_test"),
        ("delete", "/api/opportunities/opp_test"),
    ]:
        resp = getattr(client, method)(path)
        assert resp.status_code in (404, 405), (method, path, resp.status_code)
