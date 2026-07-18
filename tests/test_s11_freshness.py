"""S11: the zero-build frontend never serves stale code (static assets
revalidate), and a partial-refresh failure is surfaced, not silent."""
import json

from fastapi.testclient import TestClient

from compass.index import health_data, rebuild_index
from compass.web import create_app
from conftest import make_organisation


def _client(cfg, store):
    store.save(make_organisation(), actor="manual")
    rebuild_index(cfg, store)
    return TestClient(create_app(cfg))


def test_static_and_index_revalidate(cfg, store):
    client = _client(cfg, store)
    for path in ("/", "/static/js/main.js", "/static/js/timeline.js",
                 "/static/locales/en.json", "/static/style.css"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert "no-cache" in r.headers.get("cache-control", ""), path


def test_health_surfaces_reconcile_marker(cfg, store):
    _client(cfg, store)
    assert health_data(cfg)["reconcile"] == []
    cfg.paths.status.mkdir(parents=True, exist_ok=True)
    (cfg.paths.status / "needs_reconcile.json").write_text(
        json.dumps([{"kind": "application", "id": "app_x",
                     "at": "2026-07-19T00:00:00"}]), encoding="utf-8")
    assert len(health_data(cfg)["reconcile"]) == 1
