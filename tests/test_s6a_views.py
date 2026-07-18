"""S6a query/UI contract tests: skills radar, browser, targets, applications."""
from datetime import date, datetime, timezone

from fastapi.testclient import TestClient

from compass.index import (
    applications_data,
    browse_opportunities,
    rebuild_index,
    skills_radar,
    suggest_skill_status,
    targets_data,
)
from compass.models import (
    Application, ApplicationManual, ApplicationSystem,
    OpportunityAI, Organisation, OrganisationOfficial, OrganisationManual,
    Person, PersonOfficial,
    ScoreWithRationale, Signal, SignalOfficial,
)
from compass.rules import recompute_derived
from compass.web import create_app
from conftest import TODAY, make_opportunity, make_organisation

NOW = datetime(2026, 7, 17, tzinfo=timezone.utc)


def _ai(fit_type, rec, required=(), preferred=(), reasons=(), future=None,
        method=80):
    return OpportunityAI(
        summary="s", fit_type=fit_type,
        thematic_fit=ScoreWithRationale(score=method, rationale="r"),
        methodological_fit=ScoreWithRationale(score=method, rationale="r"),
        growth_value=ScoreWithRationale(score=50, rationale="r"),
        strategic_value=ScoreWithRationale(score=50, rationale="r"),
        required_skills=list(required), preferred_skills=list(preferred),
        rejection_reasons=list(reasons), future_group_value=future,
        recommendation=rec, confidence=0.9, model="m",
        prompt_version="fit_analysis_v1", analyzed_at=NOW,
        analysis_input_hash="h",
    )


def _seed(cfg, store):
    cfg.profile = {"skills": [
        {"id": "unity", "level": "advanced", "evidence": "Master's XR app"},
        {"id": "python", "level": "beginner", "evidence": None},
    ]}
    cfg.taxonomy = {"programming": [
        {"id": "unity", "label": "Unity"}, {"id": "python", "label": "Python"},
        {"id": "cpp", "label": "C++"},
    ]}
    uni = make_organisation()  # org_test_university, target=False
    store.save(uni, actor="manual")
    lab = Organisation(
        id="org_test_lab",
        official=OrganisationOfficial(
            name="Test XR Lab", org_type="lab", parent_org_id=uni.id
        ),
        manual=OrganisationManual(target=True, priority="high",
                                  notes="XR behaviour research"),
    )
    store.save(lab, actor="manual")
    store.save(Person(
        id="per_test_pi",
        official=PersonOfficial(name="Test PI", org_id="org_test_lab"),
    ), actor="manual")
    store.save(Signal(
        id="sig_test_expansion",
        official=SignalOfficial(signal_type="vacancy_change",
                                title="Lab hiring", org_id="org_test_lab"),
    ), actor="manual")

    fit = make_opportunity(opp_id="opp_fit", url="https://x.org/1")
    fit.official.lab_org_id = "org_test_lab"
    fit.ai = _ai("exact-fit", "apply", required=["unity", "python"],
                 preferred=["cpp"], future="high")
    fit.derived = recompute_derived(fit, cfg.constraints, TODAY)
    store.save(fit, actor="ai")

    poor = make_opportunity(opp_id="opp_poor", url="https://x.org/2",
                            deadline=date(2026, 7, 1))  # past deadline
    poor.ai = _ai("poor-fit", "reject", required=["cpp"],
                  reasons=["poor_research_fit"], future="low", method=10)
    poor.derived = recompute_derived(poor, cfg.constraints, TODAY)
    store.save(poor, actor="ai")

    store.save(Application(
        id="app_test_fit",
        system=ApplicationSystem(opportunity_id="opp_fit"),
        manual=ApplicationManual(
            stage="preparing", blockers=["confirm timing"],
            next_step="draft letter", internal_due_date=date(2026, 8, 10),
        ),
    ), actor="manual")
    rebuild_index(cfg, store)


def test_skills_radar_matches_backend_and_links_supporting(cfg, store):
    _seed(cfg, store)
    radar = skills_radar(cfg)
    tm = radar["scopes"]["target_market"]
    assert tm["total_opportunities"] == 1
    by_id = {s["skill"]: s for s in tm["skills"]}
    assert by_id["unity"]["required_count"] == 1
    assert by_id["unity"]["user_level"] == "advanced"
    assert by_id["unity"]["user_evidence"] == "Master's XR app"
    assert by_id["unity"]["supporting"] == [
        {"id": "opp_fit", "title": by_id["unity"]["supporting"][0]["title"]}
    ]
    assert by_id["cpp"]["preferred_count"] == 1
    # poor-fit cpp requirement never reaches the main radar:
    assert by_id["cpp"]["required_count"] == 0
    # but institution scope (audit-adjacent) still counts it:
    inst = radar["institutions"]["org_test_university"]
    inst_cpp = {s["skill"]: s for s in inst["skills"]}["cpp"]
    assert inst_cpp["required_count"] == 1


def test_suggest_status_rules():
    assert suggest_skill_status("advanced", 5, 0) == "strength"
    assert suggest_skill_status("intermediate", 3, 0) == "maintain"
    assert suggest_skill_status("beginner", 4, 0) == "learn_next"
    assert suggest_skill_status(None, 1, 0) == "optional"
    assert suggest_skill_status("advanced", 0, 0) == "not_relevant"


def test_browser_filters_and_audit_visibility(cfg, store):
    _seed(cfg, store)
    all_rows = browse_opportunities(cfg, {})
    assert {r["id"] for r in all_rows} == {"opp_fit", "opp_poor"}  # rejects visible

    rejected = browse_opportunities(cfg, {"rejection_reason": "poor_research_fit"})
    assert [r["id"] for r in rejected] == ["opp_poor"]

    by_skill = browse_opportunities(cfg, {"skill": "unity"})
    assert [r["id"] for r in by_skill] == ["opp_fit"]

    past = browse_opportunities(cfg, {"deadline_status": "past"})
    assert [r["id"] for r in past] == ["opp_poor"]

    by_lab = browse_opportunities(cfg, {"lab_org_id": "org_test_lab"})
    assert [r["id"] for r in by_lab] == ["opp_fit"]

    by_text = browse_opportunities(cfg, {"q": "Doctoral"})
    assert len(by_text) == 2


def test_targets_link_people_signals_vacancies_actions(cfg, store):
    _seed(cfg, store)
    targets = targets_data(cfg)
    assert len(targets) == 1
    t = targets[0]
    assert t["id"] == "org_test_lab"
    assert t["future_group_value"] == "high"
    assert [p["id"] for p in t["people"]] == ["per_test_pi"]
    assert [s["id"] for s in t["signals"]] == ["sig_test_expansion"]
    assert [o["id"] for o in t["opportunities"]] == ["opp_fit"]
    assert dict(t["recurring_skills"])["unity"] == 1
    assert t["research_direction"] == "XR behaviour research"


def test_applications_pipeline_inherits_from_vacancy(cfg, store):
    _seed(cfg, store)
    data = applications_data(cfg)
    assert data["total"] == 1
    prep = data["stages"]["preparing"]
    assert len(prep) == 1
    a = prep[0]
    assert a["official_deadline"] == "2026-08-03"   # inherited, not duplicated
    assert a["blockers"] == ["confirm timing"]
    assert a["internal_due_date"] == "2026-08-10"


def test_api_endpoints_read_only_contract(cfg, store):
    _seed(cfg, store)
    client = TestClient(create_app(cfg))
    assert client.get("/api/skills").status_code == 200
    opps = client.get("/api/opportunities?fit_type=poor-fit").json()
    assert opps["count"] == 1 and opps["opportunities"][0]["id"] == "opp_poor"
    assert client.get("/api/targets").json()["targets"][0]["id"] == "org_test_lab"
    assert client.get("/api/applications").json()["total"] == 1
    # still no write endpoints:
    for method, path in [("post", "/api/skills"), ("post", "/api/opportunities"),
                         ("put", "/api/applications"), ("delete", "/api/targets")]:
        assert getattr(client, method)(path).status_code in (404, 405)
