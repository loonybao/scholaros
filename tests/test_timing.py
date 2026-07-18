"""Graduation-horizon timing/readiness tests."""
from datetime import date, datetime, timezone

from compass.index import dashboard_data, rebuild_index
from compass.models import OpportunityAI, ScoreWithRationale
from compass.rules import (
    graduation_horizon,
    recompute_derived,
    timing_assessment,
)
from conftest import make_opportunity, make_organisation

NOW = datetime(2026, 7, 17, tzinfo=timezone.utc)
TODAY = date(2026, 7, 18)
HORIZON = {
    "expected_msc_completion": {
        "value": "2027-07", "precision": "month",
        "certainty": "estimated", "source": "user_confirmed",
    }
}


def _c(**extra):
    base = {"geography": {"allowed_regions": ["Europe"]}, "languages": ["English"],
            "requires_funding": True, "restricted_position_eligibility": None}
    base.update(extra)
    return base


def test_timing_mismatch_start_before_graduation():
    opp = make_opportunity(start_date_value=date(2026, 9, 1),
                           start_date_negotiable=True)
    assert timing_assessment(opp, _c(**HORIZON), TODAY) == "timing_mismatch"


def test_timing_unknown_when_start_not_stated():
    opp = make_opportunity()  # start_date_value None
    assert timing_assessment(opp, _c(**HORIZON), TODAY) == "timing_unknown"


def test_timing_unknown_when_no_horizon():
    opp = make_opportunity(start_date_value=date(2026, 9, 1))
    assert timing_assessment(opp, _c(), TODAY) == "timing_unknown"


def test_future_target_compatible_start_but_far_out():
    # Start after graduation, 12 months out -> compatible but too early.
    opp = make_opportunity(start_date_value=date(2027, 9, 1))
    assert timing_assessment(opp, _c(**HORIZON), TODAY) == "future_target"


def test_prepare_and_actionable_windows():
    opp = make_opportunity(start_date_value=date(2027, 9, 1))
    # 7 months out -> prepare_for_current_cycle
    assert timing_assessment(opp, _c(**HORIZON), date(2026, 12, 20)) == \
        "prepare_for_current_cycle"
    # 4 months out -> actionable_now
    assert timing_assessment(opp, _c(**HORIZON), date(2027, 3, 20)) == \
        "actionable_now"


def test_graduation_horizon_phase_and_windows():
    h = graduation_horizon(_c(**HORIZON), TODAY)
    assert h["current_phase"] == "monitor_and_build"
    assert h["expected_graduation"] == "2027-07-31"
    assert h["certainty"] == "estimated"
    assert 12 < h["months_to_graduation"] < 13
    assert h["outreach_window"] == {"from": "2027-01-31", "to": "2027-04-30"}
    assert len(h["milestones"]) == 5

    # No horizon when no expected completion.
    assert graduation_horizon(_c(), TODAY) is None


def test_horizon_phases_progress():
    assert graduation_horizon(_c(**HORIZON), date(2026, 12, 20))["current_phase"] \
        == "prepare"
    assert graduation_horizon(_c(**HORIZON), date(2027, 3, 20))["current_phase"] \
        == "outreach_window"
    assert graduation_horizon(_c(**HORIZON), date(2027, 6, 1))["current_phase"] \
        == "active_application"


def _apply_ai():
    return OpportunityAI(
        summary="s", fit_type="exact-fit",
        thematic_fit=ScoreWithRationale(score=85, rationale="r"),
        methodological_fit=ScoreWithRationale(score=88, rationale="r"),
        growth_value=ScoreWithRationale(score=75, rationale="r"),
        strategic_value=ScoreWithRationale(score=82, rationale="r"),
        recommendation="apply", future_group_value="high",
        confidence=0.85, model="m", prompt_version="fit_analysis_v1",
        analyzed_at=NOW, analysis_input_hash="h",
    )


def test_high_fit_timing_mismatch_out_of_action_required_into_intel(cfg, store):
    """High-fit apply vacancy with a start before graduation must NOT appear in
    Action Required; it becomes future-target market intelligence. Fit and
    future_group_value are preserved."""
    cfg.constraints = _c(**HORIZON)
    store.save(make_organisation(), actor="manual")
    opp = make_opportunity(start_date_value=date(2026, 9, 1),
                           start_date_negotiable=True)
    opp.ai = _apply_ai()
    opp.derived = recompute_derived(opp, cfg.constraints, TODAY)
    store.save(opp, actor="ai")
    rebuild_index(cfg, store)

    dash = dashboard_data(cfg, TODAY)
    assert dash["action_required"] == []                     # not pushed
    assert [r["id"] for r in dash["future_target_intel"]] == [opp.id]
    assert dash["graduation_horizon"]["current_phase"] == "monitor_and_build"
    # preserved:
    loaded = store.load("opportunity", opp.id)
    assert loaded.derived.fit_overall == 84
    assert loaded.ai.future_group_value == "high"
    assert loaded.derived.timing_assessment == "timing_mismatch"


def test_actionable_timing_stays_in_action_required(cfg, store):
    cfg.constraints = _c(**HORIZON)
    store.save(make_organisation(), actor="manual")
    opp = make_opportunity(start_date_value=date(2027, 9, 1),  # compatible
                           deadline=date(2027, 4, 30))          # still open then
    opp.ai = _apply_ai()
    opp.derived = recompute_derived(opp, cfg.constraints, date(2027, 3, 20))
    store.save(opp, actor="ai")
    rebuild_index(cfg, store)
    dash = dashboard_data(cfg, date(2027, 3, 20))
    assert [r["id"] for r in dash["action_required"]] == [opp.id]


def test_no_horizon_falls_back_to_fit_only(cfg, store):
    """Without a recorded graduation horizon, the timing gate is not applied."""
    cfg.constraints = _c()  # no expected_msc_completion
    store.save(make_organisation(), actor="manual")
    opp = make_opportunity()  # timing_unknown
    opp.ai = _apply_ai()
    opp.derived = recompute_derived(opp, cfg.constraints, TODAY)
    store.save(opp, actor="ai")
    rebuild_index(cfg, store)
    dash = dashboard_data(cfg, TODAY)
    assert [r["id"] for r in dash["action_required"]] == [opp.id]
    assert dash["graduation_horizon"] is None
