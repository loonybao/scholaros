from datetime import date

import pytest

from compass.rules import (
    eligibility_gate,
    expire_stale,
    propose_decision,
    urgency,
)
from conftest import TODAY, make_opportunity

FULL_CONSTRAINTS = {
    "geography": {
        "allowed_regions": ["Europe"],
        "preferred_countries": ["Finland", "Netherlands"],
        "excluded_countries": [],
    },
    "languages": ["English"],
    "excluded_language_requirements": [],
    "requires_funding": True,
    "restricted_position_eligibility": None,
}


def test_gate_pass_when_everything_known():
    opp = make_opportunity()
    gate, reasons, review = eligibility_gate(opp, FULL_CONSTRAINTS, TODAY)
    assert gate == "pass"
    assert review is False


def test_gate_uncertain_on_null_constraint():
    opp = make_opportunity()
    constraints = dict(FULL_CONSTRAINTS, geography=None)
    gate, reasons, review = eligibility_gate(opp, constraints, TODAY)
    assert gate == "uncertain"
    assert review is True
    assert any("allowed_regions" in r for r in reasons)


def test_gate_never_guesses_null_as_pass():
    opp = make_opportunity()
    all_null = {
        "geography": None,
        "languages": ["English"],
        "excluded_language_requirements": None,
        "requires_funding": True,
        "restricted_position_eligibility": None,
    }
    gate, _, review = eligibility_gate(opp, all_null, TODAY)
    assert gate == "uncertain" and review is True


def test_gate_uncertain_on_unknown_status():
    opp = make_opportunity(status="unknown")
    gate, reasons, review = eligibility_gate(opp, FULL_CONSTRAINTS, TODAY)
    assert gate == "uncertain" and review is True
    assert any("status unknown" in r for r in reasons)


def test_gate_uncertain_on_null_requires_funding():
    opp = make_opportunity()
    constraints = dict(FULL_CONSTRAINTS, requires_funding=None)
    gate, reasons, review = eligibility_gate(opp, constraints, TODAY)
    assert gate == "uncertain" and review is True
    assert any("requires_funding" in r for r in reasons)


def test_gate_fail_deadline_passed():
    opp = make_opportunity(deadline=date(2026, 7, 1))
    gate, reasons, review = eligibility_gate(opp, FULL_CONSTRAINTS, TODAY)
    assert gate == "fail"
    assert review is False


def test_gate_fail_closed_status():
    opp = make_opportunity()
    opp.official.status = "closed"
    gate, _, _ = eligibility_gate(opp, FULL_CONSTRAINTS, TODAY)
    assert gate == "fail"


def test_gate_pass_any_european_country_without_whitelist():
    """Germany is not a preferred country, but it IS Europe — the gate must
    pass; preference only affects strategic value."""
    opp = make_opportunity(location="Berlin, Germany")
    gate, reasons, review = eligibility_gate(opp, FULL_CONSTRAINTS, TODAY)
    assert gate == "pass"
    assert review is False


def test_gate_fail_outside_allowed_regions():
    opp = make_opportunity(location="Boston, United States")
    gate, reasons, _ = eligibility_gate(opp, FULL_CONSTRAINTS, TODAY)
    assert gate == "fail"
    assert any("outside allowed regions" in r for r in reasons)


def test_gate_fail_excluded_country():
    opp = make_opportunity(location="Berlin, Germany")
    constraints = dict(
        FULL_CONSTRAINTS,
        geography={
            "allowed_regions": ["Europe"],
            "preferred_countries": [],
            "excluded_countries": ["Germany"],
        },
    )
    gate, reasons, _ = eligibility_gate(opp, constraints, TODAY)
    assert gate == "fail"
    assert any("excluded_countries" in r for r in reasons)


def test_gate_uncertain_unknown_country():
    opp = make_opportunity(location=None)
    gate, reasons, review = eligibility_gate(opp, FULL_CONSTRAINTS, TODAY)
    assert gate == "uncertain"
    assert review is True
    assert any("country unknown" in r for r in reasons)


def test_preferred_country_helper_never_gates():
    from compass.rules import is_preferred_country

    assert is_preferred_country("Finland", FULL_CONSTRAINTS) is True
    assert is_preferred_country("Germany", FULL_CONSTRAINTS) is False
    assert is_preferred_country(None, FULL_CONSTRAINTS) is False


def test_gate_uncertain_unknown_language():
    opp = make_opportunity(language_requirements=["English", "Finnish"])
    gate, reasons, review = eligibility_gate(opp, FULL_CONSTRAINTS, TODAY)
    assert gate == "uncertain"
    assert any("Finnish" in r for r in reasons)


def test_gate_fail_excluded_language():
    opp = make_opportunity(language_requirements=["German"])
    constraints = dict(FULL_CONSTRAINTS, excluded_language_requirements=["German"])
    gate, _, _ = eligibility_gate(opp, constraints, TODAY)
    assert gate == "fail"


# --- degree/start timing vs expected MSc completion (estimated) ---

EST_COMPLETION = {
    "expected_msc_completion": {
        "value": "2027-07", "precision": "month",
        "certainty": "estimated", "source": "user_confirmed",
    }
}


def test_expected_completion_after_fixed_required_start_fails():
    """Completed degree required before a FIXED start that precedes the
    expected MSc completion -> hard eligibility failure."""
    opp = make_opportunity(
        completed_degree_required_before_start=True,
        start_date_value=date(2026, 9, 1),
        start_date_negotiable=False,
    )
    constraints = dict(FULL_CONSTRAINTS, **EST_COMPLETION)
    gate, reasons, review = eligibility_gate(opp, constraints, TODAY)
    assert gate == "fail"
    assert review is False
    assert any("2027-07-31" in r and "2026-09-01" in r for r in reasons)


def test_high_fit_with_timing_failure_still_rejects_but_preserves_fit():
    """High research fit can never override a degree-timing eligibility
    failure — and the failure must not erase the research-fit analysis (the
    group remains a future target; only this vacancy's viability fails)."""
    from datetime import datetime, timezone

    from compass.models import OpportunityAI, ScoreWithRationale
    from compass.rules import effective_recommendation, recompute_derived

    opp = make_opportunity(
        completed_degree_required_before_start=True,
        start_date_value=date(2026, 9, 1),
        start_date_negotiable=False,
    )
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
    constraints = dict(FULL_CONSTRAINTS, **EST_COMPLETION)
    derived = recompute_derived(opp, constraints, TODAY)
    assert derived.eligibility_gate == "fail"
    assert derived.fit_overall == 84            # research fit preserved
    assert opp.ai.thematic_fit.score == 85      # analysis untouched
    assert effective_recommendation("fail", "apply") == "reject"


def test_estimated_completion_before_start_is_never_confirmed():
    """Even when the estimate lands BEFORE the start date, an estimated date
    never passes the gate as a confirmed graduation."""
    opp = make_opportunity(
        completed_degree_required_before_start=True,
        start_date_value=date(2028, 9, 1),  # well after the 2027-07 estimate
        start_date_negotiable=False,
    )
    constraints = dict(FULL_CONSTRAINTS, **EST_COMPLETION)
    gate, reasons, review = eligibility_gate(opp, constraints, TODAY)
    assert gate == "uncertain"
    assert review is True
    assert any("estimated" in r and "not a confirmed" in r for r in reasons)


def test_negotiable_start_with_late_completion_needs_recruiter():
    """The real Tampere HTI shape: completed degree required, start stated
    but negotiable, completion after it -> uncertain + recruiter question,
    never an automatic pass or fail."""
    opp = make_opportunity(
        completed_degree_required_before_start=True,
        start_date_value=date(2026, 9, 1),
        start_date_negotiable=True,
    )
    constraints = dict(FULL_CONSTRAINTS, **EST_COMPLETION)
    gate, reasons, review = eligibility_gate(opp, constraints, TODAY)
    assert gate == "uncertain"
    assert review is True
    assert any("recruiter confirmation" in r for r in reasons)


def test_timing_requirement_not_stated_flags_verification():
    opp = make_opportunity()  # completed_degree_required_before_start=None
    constraints = dict(FULL_CONSTRAINTS, **EST_COMPLETION)
    gate, reasons, review = eligibility_gate(opp, constraints, TODAY)
    assert gate == "uncertain"
    assert any("still in progress" in r for r in reasons)


# --- nationality/export-control: opportunity-level fact, never a global gate ---

def test_no_stated_restriction_not_uncertain_despite_null_standing():
    """A position with no stated restriction must NOT become uncertain solely
    because restricted_position_eligibility is null."""
    opp = make_opportunity()  # default: nationality_restrictions_status=none_stated
    constraints = dict(FULL_CONSTRAINTS, restricted_position_eligibility=None)
    gate, reasons, review = eligibility_gate(opp, constraints, TODAY)
    assert gate == "pass"
    assert review is False
    assert not any("nationality" in r or "export-control" in r for r in reasons)


def test_stated_restriction_with_null_standing_needs_review():
    opp = make_opportunity(nationality_restrictions_status="stated")
    constraints = dict(FULL_CONSTRAINTS, restricted_position_eligibility=None)
    gate, reasons, review = eligibility_gate(opp, constraints, TODAY)
    assert gate == "uncertain"
    assert review is True
    assert any("not confirmed" in r for r in reasons)


def test_stated_restriction_with_confirmed_eligible_passes():
    opp = make_opportunity(nationality_restrictions_status="stated")
    constraints = dict(FULL_CONSTRAINTS, restricted_position_eligibility="eligible")
    gate, _, review = eligibility_gate(opp, constraints, TODAY)
    assert gate == "pass"
    assert review is False


def test_stated_restriction_with_confirmed_ineligible_fails():
    opp = make_opportunity(nationality_restrictions_status="stated")
    constraints = dict(FULL_CONSTRAINTS, restricted_position_eligibility="ineligible")
    gate, reasons, review = eligibility_gate(opp, constraints, TODAY)
    assert gate == "fail"
    assert review is False


def test_ambiguous_restriction_needs_review_even_when_eligible():
    """An ambiguous mention must be verified on the posting itself; a confirmed
    standing cannot resolve it automatically."""
    opp = make_opportunity(nationality_restrictions_status="ambiguous")
    constraints = dict(FULL_CONSTRAINTS, restricted_position_eligibility="eligible")
    gate, reasons, review = eligibility_gate(opp, constraints, TODAY)
    assert gate == "uncertain"
    assert review is True
    assert any("verify" in r for r in reasons)


def test_stated_mobility_rule_needs_review():
    opp = make_opportunity(mobility_requirement_status="stated")
    gate, reasons, review = eligibility_gate(opp, FULL_CONSTRAINTS, TODAY)
    assert gate == "uncertain" and review is True
    assert any("mobility" in r for r in reasons)


def test_no_mobility_rule_no_flag():
    opp = make_opportunity()  # default none_stated
    gate, reasons, _ = eligibility_gate(opp, FULL_CONSTRAINTS, TODAY)
    assert gate == "pass"
    assert not any("mobility" in r for r in reasons)


@pytest.mark.parametrize(
    "deadline,expected",
    [
        (None, "none"),
        (date(2026, 7, 20), "urgent"),   # 3 days
        (date(2026, 8, 3), "high"),      # 17 days
        (date(2026, 8, 25), "medium"),   # 39 days
        (date(2026, 12, 1), "low"),
    ],
)
def test_urgency(deadline, expected):
    urg, _ = urgency(deadline, TODAY)
    assert urg == expected


@pytest.mark.parametrize(
    "gate,fit,conf,expected_decision,expected_auto",
    [
        ("fail", 90, 0.9, "reject", True),
        ("pass", 80, 0.9, "apply", False),      # apply NEVER auto-finalizes
        ("pass", 65, 0.9, "consider", False),
        ("pass", 50, 0.9, "monitor", True),
        ("pass", 20, 0.9, "reject", True),
        ("uncertain", 50, 0.9, "monitor", False),  # uncertain gate blocks auto
        ("pass", 50, 0.5, "monitor", False),       # low confidence blocks auto
        ("pass", None, None, "monitor", False),
    ],
)
def test_propose_decision(gate, fit, conf, expected_decision, expected_auto):
    decision, auto = propose_decision(gate, fit, conf, confidence_threshold=0.75)
    assert decision == expected_decision
    assert auto is expected_auto


@pytest.mark.parametrize("fit", [80, 90, 100])
@pytest.mark.parametrize("conf", [0.9, 1.0])
def test_gate_fail_never_yields_apply_or_consider(fit, conf):
    """Eligibility overrides aggregate fit: no score/confidence combination
    may turn a hard eligibility failure into apply or consider."""
    decision, _ = propose_decision("fail", fit, conf, confidence_threshold=0.75)
    assert decision == "reject"


def test_effective_recommendation_clamps_on_fail():
    from compass.rules import effective_recommendation

    assert effective_recommendation("fail", "apply") == "reject"
    assert effective_recommendation("fail", "consider") == "reject"
    assert effective_recommendation("fail", "monitor") == "monitor"
    assert effective_recommendation("uncertain", "apply") == "apply"  # pending, not clamped
    assert effective_recommendation("pass", "apply") == "apply"
    assert effective_recommendation("pass", None) is None


def test_expire_stale():
    fresh = make_opportunity(deadline=date(2026, 8, 3))
    stale = make_opportunity(deadline=date(2026, 7, 1))
    assert expire_stale(fresh, TODAY) is False
    assert expire_stale(stale, TODAY) is True
