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


def test_review_queue_and_action_required(cfg, store):
    org = make_organisation()
    store.save(org, actor="manual")
    # Uncertain: stated restrictions with null standing -> needs_review.
    opp = make_opportunity(nationality_restrictions_status="stated")
    opp.derived = recompute_derived(opp, cfg.constraints, TODAY)
    store.save(opp, actor="manual")
    rebuild_index(cfg, store)

    dash = dashboard_data(cfg, TODAY)
    assert [r["id"] for r in dash["review_queue"]] == [opp.id]
    assert any(r["id"] == opp.id for r in dash["action_required"])
    assert any("not confirmed" in reason
               for reason in dash["review_queue"][0]["eligibility_reasons"])


def test_monitor_and_reject_stay_out_of_action_required(cfg, store):
    """Dispositioned records (monitor/reject) never occupy Action Required;
    they return only when a material change invalidates the analysis
    (recommendation becomes null again)."""
    from datetime import datetime, timezone

    from compass.models import OpportunityAI, ScoreWithRationale

    store.save(make_organisation(), actor="manual")
    opp = make_opportunity()  # urgency high (17d), gate pass but needs_review off
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
        analysis_input_hash="h",
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
        analysis_input_hash="h",
    )
    opp.derived = recompute_derived(opp, cfg.constraints, TODAY)
    store.save(opp, actor="manual")
    rebuild_index(cfg, store)

    dash = dashboard_data(cfg, TODAY)
    assert [r["id"] for r in dash["action_required"]] == [opp.id]


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
