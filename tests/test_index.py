from datetime import date

from compass.index import dashboard_data, health_data, rebuild_index
from compass.rules import recompute_derived
from conftest import TODAY, make_opportunity, make_organisation


def _seed(store, cfg):
    org = make_organisation()
    store.save(org, actor="manual")
    opp = make_opportunity()
    opp.derived = recompute_derived(opp, cfg.constraints, TODAY)
    store.save(opp, actor="manual")
    return org, opp


def test_rebuild_and_query(cfg, store):
    org, opp = _seed(store, cfg)
    rows = rebuild_index(cfg, store)
    assert rows == 2

    dash = dashboard_data(cfg, TODAY)
    assert len(dash["open_opportunities"]) == 1
    row = dash["open_opportunities"][0]
    assert row["id"] == opp.id
    assert row["org_name"] == "Test University"      # joined, not hard-coded
    assert row["deadline"] == "2026-08-03"
    assert row["days_to_deadline"] == 17
    assert row["urgency"] == "high"
    assert row["eligibility_gate"] == "pass"


def test_rebuild_is_idempotent(cfg, store):
    _seed(store, cfg)
    rebuild_index(cfg, store)
    rows = rebuild_index(cfg, store)  # second run must not duplicate
    assert rows == 2
    dash = dashboard_data(cfg, TODAY)
    assert len(dash["open_opportunities"]) == 1


def test_unanalyzed_goes_to_analysis_queue_not_action_required(cfg, store):
    """Queue semantics: unanalysed opportunities live in the Analysis Queue
    and never automatically occupy Action Required."""
    org = make_organisation()
    store.save(org, actor="manual")
    opp = make_opportunity(nationality_restrictions_status="stated")  # review-worthy
    opp.derived = recompute_derived(opp, cfg.constraints, TODAY)
    store.save(opp, actor="manual")
    rebuild_index(cfg, store)

    dash = dashboard_data(cfg, TODAY)
    assert dash["action_required"] == []                    # not analysed yet
    assert [r["id"] for r in dash["analysis_queue"]] == [opp.id]
    assert [r["id"] for r in dash["review_queue"]] == [opp.id]
    assert any("not confirmed" in reason
               for reason in dash["review_queue"][0]["eligibility_reasons"])


def test_monitor_and_reject_stay_out_of_action_required(cfg, store):
    """Dispositioned records (monitor/reject) never occupy Action Required;
    they return only when a material change invalidates the analysis
    (recommendation becomes null again)."""
    from datetime import datetime, timezone

    from compass.models import OpportunityAI, ScoreWithRationale

    store.save(make_organisation(), actor="manual")
    from compass.analysis_io import analysis_input_hash

    opp = make_opportunity(nationality_restrictions_status="stated")  # needs_review
    opp.ai = OpportunityAI(
        summary="s",
        fit_type="adjacent-methodological-fit",
        thematic_fit=ScoreWithRationale(score=50, rationale="r"),
        methodological_fit=ScoreWithRationale(score=50, rationale="r"),
        growth_value=ScoreWithRationale(score=50, rationale="r"),
        strategic_value=ScoreWithRationale(score=50, rationale="r"),
        recommendation="monitor",
        confidence=0.8,
        model="m",
        prompt_version="fit_analysis_v1",
        analyzed_at=datetime(2026, 7, 17, tzinfo=timezone.utc),
        analysis_input_hash=analysis_input_hash(cfg, opp),  # current, not stale
    )
    opp.derived = recompute_derived(opp, cfg.constraints, TODAY)
    store.save(opp, actor="manual")
    rebuild_index(cfg, store)

    dash = dashboard_data(cfg, TODAY)
    assert dash["action_required"] == []          # monitor stays out
    assert len(dash["review_queue"]) == 1         # but still visible in review
    assert len(dash["open_opportunities"]) == 1


def test_apply_recommendation_stays_in_action_required(cfg, store):
    from datetime import datetime, timezone

    from compass.models import OpportunityAI, ScoreWithRationale

    from compass.analysis_io import analysis_input_hash

    store.save(make_organisation(), actor="manual")
    opp = make_opportunity(nationality_restrictions_status="ambiguous")
    opp.ai = OpportunityAI(
        summary="s",
        fit_type="exact-fit",
        thematic_fit=ScoreWithRationale(score=85, rationale="r"),
        methodological_fit=ScoreWithRationale(score=88, rationale="r"),
        growth_value=ScoreWithRationale(score=75, rationale="r"),
        strategic_value=ScoreWithRationale(score=82, rationale="r"),
        recommendation="apply",
        confidence=0.85,
        model="m",
        prompt_version="fit_analysis_v1",
        analyzed_at=datetime(2026, 7, 17, tzinfo=timezone.utc),
        analysis_input_hash=analysis_input_hash(cfg, opp),
    )
    opp.derived = recompute_derived(opp, cfg.constraints, TODAY)
    store.save(opp, actor="manual")
    rebuild_index(cfg, store)

    dash = dashboard_data(cfg, TODAY)
    assert [r["id"] for r in dash["action_required"]] == [opp.id]
    assert dash["analysis_queue"] == []  # analysed record is out of the queue


def test_open_manual_tasks_in_dashboard(cfg, store):
    from compass.models import Action, ActionManual, ActionRelated, ActionSystem

    store.save(make_organisation(), actor="manual")
    act = Action(
        id="act_verify_something",
        system=ActionSystem(
            action_type="application",
            related=ActionRelated(opportunity_id="opp_x"),
            created_by="human",
            priority="high",
        ),
        manual=ActionManual(title="Verify the official clause", status="todo"),
    )
    store.save(act, actor="manual")
    rebuild_index(cfg, store)

    dash = dashboard_data(cfg, TODAY)
    assert [t["id"] for t in dash["manual_tasks"]] == ["act_verify_something"]

    act.manual.status = "done"
    store.save(act, actor="manual")
    rebuild_index(cfg, store)
    assert dashboard_data(cfg, TODAY)["manual_tasks"] == []


def test_stale_analysis_routing(cfg, store):
    """Materially changed records: a stale REJECT goes back to the Analysis
    Queue (needs re-analysis, not attention); a stale APPLY stays in Action
    Required flagged for renewed attention."""
    from datetime import datetime, timezone

    from compass.models import OpportunityAI, ScoreWithRationale

    def ai(rec, score):
        return OpportunityAI(
            summary="s",
            fit_type="poor-fit" if rec == "reject" else "exact-fit",
            thematic_fit=ScoreWithRationale(score=score, rationale="r"),
            methodological_fit=ScoreWithRationale(score=score, rationale="r"),
            growth_value=ScoreWithRationale(score=score, rationale="r"),
            strategic_value=ScoreWithRationale(score=score, rationale="r"),
            recommendation=rec,
            confidence=0.9,
            model="m",
            prompt_version="fit_analysis_v1",
            analyzed_at=datetime(2026, 7, 17, tzinfo=timezone.utc),
            analysis_input_hash="hash-of-an-older-description",  # stale
        )

    store.save(make_organisation(), actor="manual")
    rej = make_opportunity(opp_id="opp_stale_reject", url="https://example.org/1")
    rej.ai = ai("reject", 10)
    rej.derived = recompute_derived(rej, cfg.constraints, TODAY)
    store.save(rej, actor="manual")

    app = make_opportunity(opp_id="opp_stale_apply", url="https://example.org/2")
    app.ai = ai("apply", 85)
    app.derived = recompute_derived(app, cfg.constraints, TODAY)
    store.save(app, actor="manual")

    rebuild_index(cfg, store)
    dash = dashboard_data(cfg, TODAY)
    assert [r["id"] for r in dash["action_required"]] == ["opp_stale_apply"]
    assert dash["action_required"][0]["analysis_stale"] is True
    assert [r["id"] for r in dash["analysis_queue"]] == ["opp_stale_reject"]


def test_failed_gate_excluded_from_open(cfg, store):
    org = make_organisation()
    store.save(org, actor="manual")
    opp = make_opportunity(deadline=date(2026, 7, 1))  # passed deadline -> fail
    opp.derived = recompute_derived(opp, cfg.constraints, TODAY)
    store.save(opp, actor="manual")
    rebuild_index(cfg, store)

    dash = dashboard_data(cfg, TODAY)
    assert dash["open_opportunities"] == []
    assert dash["action_required"] == []


def test_hidden_opportunity_excluded(cfg, store):
    org = make_organisation()
    store.save(org, actor="manual")
    opp = make_opportunity()
    opp.derived = recompute_derived(opp, cfg.constraints, TODAY)
    opp.manual.hidden = True
    store.save(opp, actor="manual")
    rebuild_index(cfg, store)

    dash = dashboard_data(cfg, TODAY)
    assert dash["open_opportunities"] == []


def test_health_data(cfg, store):
    _seed(store, cfg)
    rebuild_index(cfg, store)
    health = health_data(cfg)
    assert health["entity_counts"]["opportunity"] == 1
    assert health["entity_counts"]["organisation"] == 1
    assert health["collectors"] == {}
    assert health["llm_configured"] is False
    assert health["index_rebuilt_at"] is not None
