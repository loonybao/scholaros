"""S6b contract tests: signal triage import, feed, watchlist, dashboard
panels, and the never-clutter-Action-Required rule."""
import json
from datetime import date, datetime, timezone

from compass.analysis_io import import_results, signal_input_hash
from compass.index import (
    dashboard_data, preparation_items, rebuild_index, signals_feed,
    skills_radar, watchlist_data,
)
from compass.models import (
    OpportunityAI, Organisation, OrganisationOfficial, OrganisationManual,
    Person, PersonOfficial, ScoreWithRationale, Signal, SignalOfficial,
)
from compass.rules import recompute_derived
from conftest import TODAY, make_opportunity, make_organisation

NOW = datetime(2026, 7, 17, tzinfo=timezone.utc)


def _seed(cfg, store):
    cfg.profile = {"skills": [
        {"id": "unity", "level": "advanced", "evidence": "XR app"},
        {"id": "statistics", "level": "beginner", "evidence": None},
    ]}
    cfg.taxonomy = {
        "programming": [{"id": "unity", "label": "Unity"}],
        "research_methods": [{"id": "statistics", "label": "Statistics"}],
    }
    store.save(make_organisation(), actor="manual")
    lab = Organisation(
        id="org_test_lab",
        official=OrganisationOfficial(name="Test XR Lab", org_type="lab",
                                      parent_org_id="org_test_university"),
        manual=OrganisationManual(target=True, priority="high", notes="XR lab"),
    )
    store.save(lab, actor="manual")
    store.save(Person(id="per_test_pi",
                      official=PersonOfficial(name="Test PI", org_id="org_test_lab",
                                              title="Professor")),
               actor="manual")

    opp = make_opportunity(opp_id="opp_fit", url="https://x.org/1")
    opp.official.lab_org_id = "org_test_lab"
    opp.ai = OpportunityAI(
        summary="s", fit_type="exact-fit",
        thematic_fit=ScoreWithRationale(score=85, rationale="r"),
        methodological_fit=ScoreWithRationale(score=85, rationale="r"),
        growth_value=ScoreWithRationale(score=60, rationale="r"),
        strategic_value=ScoreWithRationale(score=70, rationale="r"),
        required_skills=["unity", "statistics"], future_group_value="high",
        recommendation="apply", confidence=0.9, model="m",
        prompt_version="fit_analysis_v1", analyzed_at=NOW,
        analysis_input_hash="h",
    )
    opp.derived = recompute_derived(opp, cfg.constraints, TODAY)
    store.save(opp, actor="ai")

    sig = Signal(
        id="sig_test_lab_expansion",
        official=SignalOfficial(
            signal_type="vacancy_change", title="Lab hiring at two levels",
            org_id="org_test_lab", url="https://x.org/jobs",
            published_at=date(2026, 7, 15), retrieved_at=NOW,
            excerpt="Two concurrent openings.", person_ids=["per_test_pi"],
        ),
    )
    store.save(sig, actor="manual")
    return sig


def _triage(cfg, store, sig, likelihood="high"):
    result = {"results": [{"id": sig.id, "entity": "signal", "analysis": {
        "analysis_input_hash": signal_input_hash(cfg, sig),
        "relevance_score": 85, "strength": "high",
        "implications": "aligned", "possible_future_recruitment": True,
        "recruitment_likelihood": likelihood,
        "recruitment_rationale": "methodologically aligned concurrent hiring",
        "risks": ["wave may pass"],
        "related_opportunity_ids": ["opp_fit"],
        "confidence": 0.9,
    }}]}
    path = cfg.paths.root / "r.json"
    path.write_text(json.dumps(result), encoding="utf-8")
    return import_results(cfg, store, path, model="claude-fable-5")


def test_signal_triage_import_writes_ai_only(cfg, store):
    sig = _seed(cfg, store)
    report = _triage(cfg, store, sig)
    assert report["imported"] == [sig.id] and not report["rejected"]
    loaded = store.load("signal", sig.id)
    assert loaded.ai.recruitment_likelihood == "high"
    assert loaded.ai.analysis_provider == "interactive_claude"
    assert loaded.official.title == "Lab hiring at two levels"  # untouched
    assert loaded.change_history[-1].actor == "ai"


def test_signal_import_rejects_stale_and_fact_smuggling(cfg, store):
    sig = _seed(cfg, store)
    bad = {"results": [{"id": sig.id, "entity": "signal", "analysis": {
        "analysis_input_hash": "wrong", "relevance_score": 10,
        "strength": "low", "confidence": 0.5,
    }}]}
    p = cfg.paths.root / "bad.json"
    p.write_text(json.dumps(bad), encoding="utf-8")
    assert "stale" in import_results(cfg, store, p, model="m")["rejected"][0]

    smuggle = {"results": [{"id": sig.id, "entity": "signal", "analysis": {
        "analysis_input_hash": signal_input_hash(cfg, sig),
        "relevance_score": 10, "strength": "low", "confidence": 0.5,
        "url": "https://fake.example",
    }}]}
    p.write_text(json.dumps(smuggle), encoding="utf-8")
    assert "forbidden" in import_results(cfg, store, p, model="m")["rejected"][0]


def test_feed_watchlist_and_dashboard_panels(cfg, store):
    sig = _seed(cfg, store)
    _triage(cfg, store, sig)
    rebuild_index(cfg, store)

    feed = signals_feed(cfg)
    assert len(feed) == 1
    s = feed[0]
    assert s["recruitment_likelihood"] == "high"
    assert [p["id"] for p in s["people"]] == ["per_test_pi"]
    assert [o["id"] for o in s["opportunities"]] == ["opp_fit"]

    wl = watchlist_data(cfg)
    t = next(t for t in wl if t["id"] == "org_test_lab")
    assert t["recruitment_likelihood"] == "high"
    assert t["last_checked"] is not None
    # Structured, localisable preparation items (no baked-in English).
    kinds = {i["kind"] for i in t["preparation_items"]}
    skills = {i.get("skill") for i in t["preparation_items"]}
    assert "statistics" in skills       # beginner + required -> strengthen
    assert "portfolio" in kinds or "unity" in skills  # advanced -> portfolio
    assert "monitor_person" in kinds
    assert t["next_preparation"]

    dash = dashboard_data(cfg, TODAY)
    assert [s["id"] for s in dash["recent_signals"]] == [sig.id]
    assert any(w["id"] == "org_test_lab" and w["recruitment_likelihood"] == "high"
               for w in dash["watchlist"])
    assert dash["preparation_actions"]
    # Signals never clutter Action Required:
    assert all(r["id"] != sig.id for r in dash["action_required"])


def test_radar_institutions_use_formal_names(cfg, store):
    _seed(cfg, store)
    rebuild_index(cfg, store)
    radar = skills_radar(cfg)
    assert radar["institutions"]["org_test_university"]["name"] == "Test University"
