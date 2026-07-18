"""Pure rule functions: eligibility gate, urgency, fit aggregation, decision
proposal. No I/O. Everything here is recomputable at any time.

Null-constraint semantics (see CLAUDE.md): unknown hard constraints are never
guessed. A check that depends on a null constraint yields 'uncertain' and sets
needs_review — it can never produce 'pass' on its own.
"""

from __future__ import annotations

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
