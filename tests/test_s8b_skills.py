"""S8b: skill-progress tracking — the effective profile is baseline
(current_profile.yaml) overlaid with audited SkillProgress; web writes go to the
canonical entity only, never to the baseline config."""
import pytest
from fastapi.testclient import TestClient

from compass.index import effective_profile_skills, rebuild_index, skills_radar
from compass.rules import recompute_derived
from compass.web import create_app
from conftest import TODAY, make_opportunity, make_organisation


def _client(cfg, store):
    cfg.profile = {"skills": [{"id": "python", "level": "beginner", "evidence": "none"}]}
    cfg.taxonomy = {"programming": [{"id": "python", "label": "Python"},
                                    {"id": "statistics", "label": "Statistics"}]}
    store.save(make_organisation(), actor="manual")
    opp = make_opportunity()
    opp.derived = recompute_derived(opp, cfg.constraints, TODAY)
    store.save(opp, actor="manual")
    rebuild_index(cfg, store)
    return TestClient(create_app(cfg)), opp.id


def test_set_progress_creates_entity_and_overrides_baseline(cfg, store):
    client, _ = _client(cfg, store)
    r = client.put("/api/skills/python/progress", json={
        "current_level": "intermediate", "learning_status": "learning",
        "target_level": "advanced", "evidence": "Built a data pipeline"})
    assert r.status_code == 200
    assert store.exists("skill_progress", "skp_python")
    sp = store.load("skill_progress", "skp_python")
    assert sp.manual.current_level == "intermediate"
    assert sp.manual.target_level == "advanced"
    assert sp.change_history[-1].actor == "user"
    # effective profile reflects the override; baseline config is untouched
    eff = {s["id"]: s for s in effective_profile_skills(cfg)}
    assert eff["python"]["level"] == "intermediate"
    assert eff["python"]["learning_status"] == "learning"
    assert cfg.profile["skills"][0]["level"] == "beginner"     # baseline unchanged


def test_progress_shows_in_radar_board(cfg, store):
    client, _ = _client(cfg, store)
    client.put("/api/skills/python/progress", json={"current_level": "advanced"})
    board = {s["skill"]: s for s in skills_radar(cfg)["profile_board"]}
    assert board["python"]["level"] == "advanced"
    assert board["python"]["tracked"] is True
    # a baseline-only skill is present but not marked tracked
    assert board["python"]["label"] == "Python"


def test_can_track_a_skill_absent_from_baseline(cfg, store):
    client, _ = _client(cfg, store)
    r = client.put("/api/skills/statistics/progress",
                   json={"current_level": "beginner", "learning_status": "learning"})
    assert r.status_code == 200
    eff = {s["id"]: s for s in effective_profile_skills(cfg)}
    assert eff["statistics"]["level"] == "beginner" and eff["statistics"]["tracked"]


def test_unknown_skill_rejected(cfg, store):
    client, _ = _client(cfg, store)
    assert client.put("/api/skills/not-a-skill/progress",
                      json={"current_level": "advanced"}).status_code == 400


def test_progress_stale_write_rejected(cfg, store):
    client, _ = _client(cfg, store)
    v = client.put("/api/skills/python/progress", json={"notes": "a"}).json()["updated_at"]
    client.put("/api/skills/python/progress", json={"notes": "b"})
    r = client.put("/api/skills/python/progress",
                   json={"expected_updated_at": v, "notes": "c"})
    assert r.status_code == 409


def test_progress_extra_fields_forbidden(cfg, store):
    client, _ = _client(cfg, store)
    # 'level' is not a field (it's current_level); extra=forbid blocks smuggling
    assert client.put("/api/skills/python/progress",
                      json={"level": "advanced"}).status_code == 422
