from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from compass.index import (
    analytics_scopes,
    dashboard_data,
    rebuild_index,
    skills_analytics,
)
from compass.models import OpportunityAI, ScoreWithRationale
from compass.rules import recompute_derived
from conftest import TODAY, make_opportunity, make_organisation

NOW = datetime(2026, 7, 17, tzinfo=timezone.utc)


def _ai(fit_type, rec, method_score, reasons=(), required=(), preferred=(),
        evidence=None, future=None):
    return OpportunityAI(
        summary="s",
        fit_type=fit_type,
        thematic_fit=ScoreWithRationale(score=method_score, rationale="r"),
        methodological_fit=ScoreWithRationale(score=method_score, rationale="r"),
        growth_value=ScoreWithRationale(score=50, rationale="r"),
        strategic_value=ScoreWithRationale(score=50, rationale="r"),
        required_skills=list(required),
        preferred_skills=list(preferred),
        skill_evidence=evidence or {},
        rejection_reasons=list(reasons),
        future_group_value=future,
        recommendation=rec,
        confidence=0.9,
        model="m",
        prompt_version="fit_analysis_v1",
        analyzed_at=NOW,
        analysis_input_hash="h",
    )


def test_invalid_rejection_reason_rejected():
    with pytest.raises(ValidationError):
        _ai("poor-fit", "reject", 10, reasons=["because_i_said_so"])


def test_reject_preserves_intelligence_in_full_audit(cfg, store):
    """A rejected opportunity is never deleted: it stays in canonical, in the
    index, and in the full audit count — with fit and future-group value
    separated from the vacancy decision."""
    store.save(make_organisation(), actor="manual")
    opp = make_opportunity()
    opp.ai = _ai(
        "exact-fit", "reject", 88,
        reasons=["degree_timing_mismatch"], future="high",
        required=["unity"],
    )
    opp.derived = recompute_derived(opp, cfg.constraints, TODAY)
    store.save(opp, actor="ai")
    rebuild_index(cfg, store)

    assert store.exists("opportunity", opp.id)           # canonical intact
    stats = skills_analytics(cfg)
    assert stats["full_audit_count"] == 1                # audit keeps it
    loaded = store.load("opportunity", opp.id)
    assert loaded.ai.methodological_fit.score == 88      # alignment preserved
    assert loaded.ai.future_group_value == "high"        # future value separate
    assert loaded.ai.rejection_reasons == ["degree_timing_mismatch"]


def test_scope_membership():
    # Poor-fit engineering vacancy: audit only, no personal scopes.
    assert analytics_scopes({
        "fit_type": "poor-fit", "recommendation": "reject",
        "eligibility_gate": "uncertain", "methodological_fit": 10,
        "rejection_reasons": ["poor_research_fit"],
    }) == []

    # Apply on an exact fit: target market + actionable.
    assert analytics_scopes({
        "fit_type": "exact-fit", "recommendation": "apply",
        "eligibility_gate": "uncertain", "methodological_fit": 88,
        "rejection_reasons": [],
    }) == ["target_market", "actionable"]

    # Career-stage-only reject with high methodological fit: future target.
    scopes = analytics_scopes({
        "fit_type": "exact-fit", "recommendation": "reject",
        "eligibility_gate": "uncertain", "methodological_fit": 80,
        "rejection_reasons": ["career_stage_mismatch"],
    })
    assert "future_target" in scopes and "target_market" in scopes

    # Reject that includes a research-fit reason is NOT a future target.
    assert "future_target" not in analytics_scopes({
        "fit_type": "adjacent-methodological-fit", "recommendation": "reject",
        "eligibility_gate": "uncertain", "methodological_fit": 70,
        "rejection_reasons": ["career_stage_mismatch", "poor_research_fit"],
    })

    # Monitor with failed gate is not actionable.
    assert "actionable" not in analytics_scopes({
        "fit_type": "adjacent-methodological-fit", "recommendation": "monitor",
        "eligibility_gate": "fail", "methodological_fit": 70,
        "rejection_reasons": [],
    })


def test_skills_analytics_scopes_and_required_vs_preferred(cfg, store):
    store.save(make_organisation(), actor="manual")

    fit = make_opportunity(opp_id="opp_fit", url="https://example.org/f")
    fit.ai = _ai("exact-fit", "apply", 88,
                 required=["unity", "user-studies"], preferred=["python"],
                 evidence={"unity": "Unity/Unreal game engine"})
    fit.derived = recompute_derived(fit, cfg.constraints, TODAY)
    store.save(fit, actor="ai")

    poor = make_opportunity(opp_id="opp_poor", url="https://example.org/p")
    poor.ai = _ai("poor-fit", "reject", 10,
                  reasons=["poor_research_fit"], required=["cpp"])
    poor.derived = recompute_derived(poor, cfg.constraints, TODAY)
    store.save(poor, actor="ai")

    rebuild_index(cfg, store)
    stats = skills_analytics(cfg)

    # Main radar scope: poor-fit cpp never appears; required vs preferred split.
    tm = stats["target_market"]
    assert tm["opportunities"] == 1
    assert tm["required"] == {"unity": 1, "user-studies": 1}
    assert tm["preferred"] == {"python": 1}
    assert "cpp" not in tm["required"]

    # Full audit still counts both.
    assert stats["full_audit_count"] == 2

    # Institution scope contains both (separately auditable).
    inst = stats["institution_specific"]["org_test_university"]
    assert inst["opportunities"] == 2
    assert inst["required"]["cpp"] == 1


def test_skill_evidence_round_trip(cfg, store):
    opp = make_opportunity()
    opp.ai = _ai("exact-fit", "apply", 85, required=["unity"],
                 evidence={"unity": "developing XR applications using Unity"})
    store.save(opp, actor="ai")
    loaded = store.load("opportunity", opp.id)
    assert loaded.ai.skill_evidence["unity"].startswith("developing XR")
