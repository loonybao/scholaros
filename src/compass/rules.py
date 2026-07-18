"""Pure rule functions: eligibility gate, urgency, fit aggregation, decision
proposal. No I/O. Everything here is recomputable at any time.

Null-constraint semantics (see CLAUDE.md): unknown hard constraints are never
guessed. A check that depends on a null constraint yields 'uncertain' and sets
needs_review — it can never produce 'pass' on its own.
"""

from __future__ import annotations

import calendar
from datetime import date
from typing import Any, Optional

from .models import (
    DecisionBasis,
    Opportunity,
    OpportunityDerived,
)

FIT_WEIGHTS = {
    "thematic": 0.35,
    "methodological": 0.35,
    "growth": 0.15,
    "strategic": 0.15,
}

# Mechanical region membership for the geography gate. Council-of-Europe-style
# wide definition; being here says nothing about visas or eligibility.
EUROPE_COUNTRIES = {
    "Albania", "Andorra", "Austria", "Belgium", "Bosnia and Herzegovina",
    "Bulgaria", "Croatia", "Cyprus", "Czech Republic", "Czechia", "Denmark",
    "Estonia", "Finland", "France", "Germany", "Greece", "Hungary", "Iceland",
    "Ireland", "Italy", "Latvia", "Liechtenstein", "Lithuania", "Luxembourg",
    "Malta", "Moldova", "Monaco", "Montenegro", "Netherlands",
    "North Macedonia", "Norway", "Poland", "Portugal", "Romania", "San Marino",
    "Serbia", "Slovakia", "Slovenia", "Spain", "Sweden", "Switzerland",
    "Ukraine", "United Kingdom", "UK",
}

REGION_MEMBERS = {"Europe": EUROPE_COUNTRIES}


def is_preferred_country(country: Optional[str], constraints: dict[str, Any]) -> bool:
    """Preference feeds strategic value (S4+); it NEVER affects the gate."""
    geo = constraints.get("geography") or {}
    return bool(country) and country in (geo.get("preferred_countries") or [])


def expected_completion(constraints: dict[str, Any]) -> tuple[Optional[date], Optional[str]]:
    """Parse constraints.expected_msc_completion -> (date, certainty).

    Month precision resolves to the LAST day of the month (conservative).
    The certainty tag is carried so an 'estimated' date is never treated as a
    confirmed graduation."""
    raw = constraints.get("expected_msc_completion")
    if not isinstance(raw, dict) or not raw.get("value"):
        return None, None
    value = str(raw["value"])
    certainty = raw.get("certainty") or "estimated"
    try:
        if raw.get("precision") == "month" or len(value) == 7:
            year, month = int(value[:4]), int(value[5:7])
            return date(year, month, calendar.monthrange(year, month)[1]), certainty
        return date.fromisoformat(value), certainty
    except (ValueError, IndexError):
        return None, None


def months_between(start: date, end: date) -> float:
    """Approximate whole-plus-fractional months from start to end."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    return months + (end.day - start.day) / 30.0


def _minus_months(d: date, n: int) -> date:
    total = d.year * 12 + (d.month - 1) - n
    year, month = divmod(total, 12)
    month += 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last))


def timing_assessment(
    opp: Opportunity, constraints: dict[str, Any], today: date
) -> str:
    """Deterministic timing/readiness of THIS vacancy given the user's
    expected MSc completion. Never guesses a start date; an estimated
    completion is used for planning but is not treated as confirmed.

    Returns one of: actionable_now, prepare_for_current_cycle, future_target,
    timing_mismatch, timing_unknown.
    """
    exp_grad, _certainty = expected_completion(constraints)
    if exp_grad is None:
        return "timing_unknown"  # no horizon to assess against
    start = opp.official.start_date_value
    if start is None:
        return "timing_unknown"  # start not stated on the posting
    if start < exp_grad:
        # The position begins before the user can start. A ~months-long gap is
        # not something 'negotiable' realistically bridges; treat as a mismatch.
        return "timing_mismatch"
    months = months_between(today, exp_grad)
    if months > 9:
        return "future_target"           # compatible start, but too early to act
    if months > 6:
        return "prepare_for_current_cycle"
    return "actionable_now"


# Planning phase thresholds in months-to-graduation.
def graduation_horizon(
    constraints: dict[str, Any], today: date
) -> Optional[dict[str, Any]]:
    """Deterministic career-timing plan from the expected MSc completion.
    Returns None when no expected completion is recorded (no horizon)."""
    exp_grad, certainty = expected_completion(constraints)
    if exp_grad is None:
        return None
    months = months_between(today, exp_grad)

    if months > 9:
        phase, label, guidance = (
            "monitor_and_build",
            "Monitor & capability building",
            "Monitor target groups, build skills, and finish thesis and "
            "publications. Do not initiate recruiter outreach for ordinary "
            "live vacancies this far from graduation.",
        )
    elif months > 6:
        phase, label, guidance = (
            "prepare",
            "Application preparation",
            "Begin application preparation and target-lab research.",
        )
    elif months > 3:
        phase, label, guidance = (
            "outreach_window",
            "Recruiter/supervisor outreach",
            "Recruiter or supervisor outreach may become appropriate for "
            "relevant live vacancies with a compatible start date.",
        )
    else:
        phase, label, guidance = (
            "active_application",
            "Active applications",
            "Actively apply, prioritising roles whose start date is compatible "
            "with your MSc completion.",
        )

    prep_from = _minus_months(exp_grad, 9)
    outreach_from = _minus_months(exp_grad, 6)
    active_from = _minus_months(exp_grad, 6)
    final_push = _minus_months(exp_grad, 3)

    # Structured milestones: the frontend localises via t(key). No English text
    # is baked in here (dynamic-content localisation).
    milestones = [
        {"date": today.isoformat(), "key": "milestone.now"},
        {"date": prep_from.isoformat(), "key": "milestone.prepare"},
        {"date": outreach_from.isoformat(), "key": "milestone.outreach"},
        {"date": final_push.isoformat(), "key": "milestone.active"},
        {"date": exp_grad.isoformat(), "key": "milestone.graduation",
         "certainty": certainty},
    ]

    return {
        "expected_graduation": exp_grad.isoformat(),
        "certainty": certainty,
        "months_to_graduation": round(months, 1),
        "current_phase": phase,
        "phase_label": label,
        "phase_guidance": guidance,
        "outreach_window": {"from": outreach_from.isoformat(),
                            "to": final_push.isoformat()},
        "active_application_window": {"from": active_from.isoformat(),
                                     "to": exp_grad.isoformat()},
        "preparation_window": {"from": prep_from.isoformat(),
                              "to": outreach_from.isoformat()},
        "milestones": milestones,
    }


def urgency(deadline: Optional[date], today: date) -> tuple[str, Optional[int]]:
    if deadline is None:
        return "none", None
    days = (deadline - today).days
    if days < 0:
        return "none", days
    if days <= 7:
        return "urgent", days
    if days <= 21:
        return "high", days
    if days <= 45:
        return "medium", days
    return "low", days


def eligibility_gate(
    opp: Opportunity, constraints: dict[str, Any], today: date
) -> tuple[str, list[str], bool]:
    """Return (gate, reasons, needs_review).

    fail    — a hard check definitively fails (deadline passed, closed, country
              excluded, language requirement known-unmeetable)
    uncertain — at least one check depends on a null constraint or unknown fact
    pass    — every applicable check passes on known information
    """
    reasons: list[str] = []
    uncertain = False

    # Deadline / status: hard facts.
    if opp.official.status in ("closed", "expired"):
        return "fail", [f"position status is {opp.official.status}"], False
    if opp.official.deadline is not None and opp.official.deadline < today:
        return "fail", ["application deadline has passed"], False
    if opp.official.status == "unknown":
        reasons.append("position status unknown — verify it is still open")
        uncertain = True
    if opp.official.deadline is None:
        reasons.append("deadline unknown — verify on the official page")
        uncertain = True

    # Geography. Regions gate; preferred countries do NOT (strategic only).
    geo = constraints.get("geography")
    country = _country_of(opp)
    if not geo or geo.get("allowed_regions") is None:
        reasons.append("geography.allowed_regions not set in constraints.yaml")
        uncertain = True
    elif country is None:
        reasons.append("position country unknown")
        uncertain = True
    elif country in (geo.get("excluded_countries") or []):
        return "fail", [f"country '{country}' is in excluded_countries"], False
    else:
        in_region = any(
            country in REGION_MEMBERS.get(region, set())
            for region in geo["allowed_regions"]
        )
        if not in_region:
            return (
                "fail",
                [f"country '{country}' is outside allowed regions "
                 f"{geo['allowed_regions']}"],
                False,
            )

    # Language requirements.
    languages = constraints.get("languages") or []
    excluded_langs = constraints.get("excluded_language_requirements")
    for req in opp.official.language_requirements:
        if req in languages:
            continue
        if excluded_langs is not None and req in excluded_langs:
            return "fail", [f"required language '{req}' is known-unmeetable"], False
        reasons.append(f"required language '{req}' not confirmed in constraints")
        uncertain = True

    # Funding requirement. null is unknown, not "no requirement".
    requires_funding = constraints.get("requires_funding")
    if requires_funding is None:
        reasons.append("requires_funding not set in constraints.yaml (null)")
        uncertain = True
    elif requires_funding:
        if not opp.official.funding and not opp.official.salary_text:
            reasons.append("funding/salary not confirmed on the posting")
            uncertain = True

    # Nationality / export-control restrictions: opportunity-specific fact.
    # A position with NO stated restriction is never made uncertain by this
    # dimension, regardless of the user's constraint value. The user's
    # nationality/visa/clearance standing is never assumed or invented.
    r_status = opp.official.nationality_restrictions_status
    if r_status == "ambiguous":
        reasons.append(
            "posting mentions possible nationality/export-control restrictions "
            "— verify which roles are affected"
        )
        uncertain = True
    elif r_status == "stated":
        standing = constraints.get("restricted_position_eligibility")
        if standing == "ineligible":
            return (
                "fail",
                ["position states nationality/export-control restrictions and "
                 "your confirmed standing is 'ineligible'"],
                False,
            )
        if standing == "eligible":
            pass  # confirmed eligible for restricted positions; no flag
        else:  # null / unknown — never guess
            reasons.append(
                "position states nationality/export-control restrictions; your "
                "eligibility standing is not confirmed (null)"
            )
            uncertain = True

    # Degree/start timing: deterministic check of the user's expected MSc
    # completion against the position's stated requirements. An ESTIMATED
    # completion date is never treated as a confirmed graduation; the date is
    # never adjusted to make a vacancy appear eligible.
    exp_date, certainty = expected_completion(constraints)
    req = opp.official.completed_degree_required_before_start
    start = opp.official.start_date_value
    negotiable = opp.official.start_date_negotiable
    if req is True:
        if exp_date is None:
            reasons.append(
                "completed degree required before start; your expected MSc "
                "completion is not recorded"
            )
            uncertain = True
        elif start is not None and exp_date > start:
            if negotiable is True:
                reasons.append(
                    f"completed degree required and expected MSc completion "
                    f"({exp_date.isoformat()}, {certainty}) is after the "
                    f"stated-but-negotiable start {start.isoformat()} — "
                    f"recruiter confirmation required"
                )
                uncertain = True
            else:
                return (
                    "fail",
                    [f"completed degree required before the start date "
                     f"{start.isoformat()} (not stated as negotiable); expected "
                     f"MSc completion ({exp_date.isoformat()}, {certainty}) is "
                     f"after it"],
                    False,
                )
        elif start is not None:
            reasons.append(
                f"expected MSc completion ({exp_date.isoformat()}) is before "
                f"the start, but it is {certainty} — not a confirmed "
                f"graduation; verify before relying on it"
            )
            uncertain = True
        else:
            reasons.append(
                "completed degree required before start, but the start date "
                "is not stated — verify timing"
            )
            uncertain = True
    elif req is None and exp_date is not None:
        reasons.append(
            "whether a completed degree is required before employment is not "
            "stated; your MSc is still in progress — verify with the source"
        )
        uncertain = True

    # Mobility/residence-history rules: separate from nationality/export
    # control. The applicant's residence history is not held in constraints,
    # so a stated/ambiguous rule always needs human verification.
    m_status = opp.official.mobility_requirement_status
    if m_status == "ambiguous":
        reasons.append(
            "posting hints at a mobility/residence-history rule — verify the exact condition"
        )
        uncertain = True
    elif m_status == "stated":
        reasons.append(
            "posting states a mobility/residence-history rule — verify you satisfy it"
        )
        uncertain = True

    if uncertain:
        return "uncertain", reasons, True
    return "pass", reasons, False


def compute_fit_overall(ai: Any) -> Optional[int]:
    if ai is None:
        return None
    total = (
        ai.thematic_fit.score * FIT_WEIGHTS["thematic"]
        + ai.methodological_fit.score * FIT_WEIGHTS["methodological"]
        + ai.growth_value.score * FIT_WEIGHTS["growth"]
        + ai.strategic_value.score * FIT_WEIGHTS["strategic"]
    )
    return round(total)


def propose_decision(
    gate: str,
    fit_overall: Optional[int],
    confidence: Optional[float],
    confidence_threshold: float,
) -> tuple[str, bool]:
    """Return (proposed_decision, may_auto_finalize).

    - apply is NEVER auto-finalized.
    - gate=uncertain or low confidence -> never auto-finalize.
    """
    if gate == "fail":
        proposed = "reject"
    elif fit_overall is None:
        proposed = "monitor"
    elif fit_overall >= 75:
        proposed = "apply"
    elif fit_overall >= 60:
        proposed = "consider"
    elif fit_overall >= 40:
        proposed = "monitor"
    else:
        proposed = "reject"

    may_auto = (
        proposed in ("monitor", "reject")
        and gate != "uncertain"
        and confidence is not None
        and confidence >= confidence_threshold
    )
    return proposed, may_auto


# Application stage machine. Forward transitions only; withdrawal is always
# allowed. A same-stage set is a no-op. Anything else needs an explicit
# correction (recorded as an audited user change), never a silent overwrite.
APPLICATION_TRANSITIONS: dict[str, set[str]] = {
    "identified": {"preparing", "monitoring", "withdrawn"},
    "preparing": {"submitted", "monitoring", "withdrawn"},
    "monitoring": {"preparing", "submitted", "withdrawn"},
    "submitted": {"interview", "offered", "rejected", "awaiting_response", "withdrawn"},
    "awaiting_response": {"interview", "offered", "rejected", "withdrawn"},
    "interview": {"offered", "rejected", "withdrawn"},
    "offered": {"withdrawn"},
    "rejected": set(),
    "withdrawn": set(),
}


def valid_application_transition(frm: str, to: str) -> bool:
    """True if `to` is a permitted forward transition from `frm` (or a no-op)."""
    return to == frm or to in APPLICATION_TRANSITIONS.get(frm, set())


def effective_recommendation(gate: str, ai_recommendation: Optional[str]) -> Optional[str]:
    """Eligibility overrides aggregate fit: a hard gate failure clamps any
    AI recommendation to reject — apply/consider can never survive it."""
    if ai_recommendation is None:
        return None
    if gate == "fail" and ai_recommendation in ("apply", "consider"):
        return "reject"
    return ai_recommendation


def recompute_derived(
    opp: Opportunity, constraints: dict[str, Any], today: date
) -> OpportunityDerived:
    gate, reasons, needs_review = eligibility_gate(opp, constraints, today)
    urg, days = urgency(opp.official.deadline, today)
    fit = compute_fit_overall(opp.ai)
    if opp.ai is not None and opp.ai.confidence < 0.5:
        needs_review = True
    return OpportunityDerived(
        eligibility_gate=gate,
        eligibility_reasons=reasons,
        fit_overall=fit,
        urgency=urg,
        days_to_deadline=days,
        needs_review=needs_review,
        timing_assessment=timing_assessment(opp, constraints, today),
    )


def expire_stale(opp: Opportunity, today: date) -> bool:
    """Return True if the opportunity should transition open->expired."""
    return (
        opp.official.status == "open"
        and opp.official.deadline is not None
        and opp.official.deadline < today
    )


def decision_basis(opp: Opportunity) -> DecisionBasis:
    ai = opp.ai
    return DecisionBasis(
        eligibility_gate=opp.derived.eligibility_gate,
        fit_overall=opp.derived.fit_overall,
        thematic=ai.thematic_fit.score if ai else None,
        methodological=ai.methodological_fit.score if ai else None,
        growth=ai.growth_value.score if ai else None,
        strategic=ai.strategic_value.score if ai else None,
        confidence=ai.confidence if ai else None,
    )


def _country_of(opp: Opportunity) -> Optional[str]:
    loc = opp.official.location
    if not loc:
        return None
    # location convention: "City, Country" or just "Country"
    return loc.split(",")[-1].strip() or None
