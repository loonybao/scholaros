"""Pydantic models for the 7 canonical entities.

Field-layer ownership (see CLAUDE.md):
  official.* — collectors / manual entry only, with provenance
  ai.*       — analyze stage only; deliberately contains NO fact fields
  derived.*  — computed by rules.py, always recomputable
  manual.*   — human only; automation must never modify
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = 10

# Structured rejection reasons. A reject decision NEVER deletes opportunity
# intelligence — records stay browsable for history and skill analytics; the
# reasons make the rejection auditable and let timing/career-stage rejects be
# distinguished from research-fit rejects.
RejectionReason = Literal[
    "poor_research_fit",
    "eligibility_mismatch",
    "degree_timing_mismatch",
    "career_stage_mismatch",
    "unpaid_or_self_funded",
    "language_requirement",
    "mobility_or_location_constraint",
    "deadline_passed",
    "user_not_interested",
]

ID_PREFIXES = {
    "opportunity": "opp_",
    "organisation": "org_",
    "person": "per_",
    "signal": "sig_",
    "decision": "dec_",
    "action": "act_",
    "application": "app_",
    "skill_progress": "skp_",
}

Actor = str  # "collector:aalto" | "manual" | "ai" | "rules" | "human" | "migration"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ChangeEntry(BaseModel):
    ts: datetime
    actor: Actor
    fields_changed: list[str]
    note: Optional[str] = None


# IDs become filenames: safe charset only, no path separators / dots / colons.
_VALID_ID = re.compile(
    r"^(opp_|org_|per_|sig_|dec_|act_|app_|skp_)[a-z0-9][a-z0-9_-]*$"
)


class Envelope(BaseModel):
    """Common envelope for every canonical entity."""

    model_config = ConfigDict(extra="forbid")

    id: str
    entity_type: str
    schema_version: int = SCHEMA_VERSION
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    change_history: list[ChangeEntry] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _id_is_filesystem_safe(cls, v: str) -> str:
        if not _VALID_ID.match(v):
            raise ValueError(
                f"invalid entity id {v!r}: must match {_VALID_ID.pattern} "
                "(ids become filenames; no path separators or special chars)"
            )
        return v


class ScoreWithRationale(BaseModel):
    model_config = ConfigDict(extra="forbid")
    score: int = Field(ge=0, le=100)
    rationale: str


# --------------------------------------------------------------------------- #
# Opportunity
# --------------------------------------------------------------------------- #

class OpportunityOfficial(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    org_id: str
    lab_org_id: Optional[str] = None
    source: str  # collector id or "manual"
    source_native_id: Optional[str] = None  # identity priority 1
    canonical_url: str  # identity priority 2
    apply_url: Optional[str] = None
    evidence_ids: list[str] = Field(default_factory=list)
    retrieved_at: datetime
    raw_snapshot_hash: Optional[str] = None
    extracted_content_hash: Optional[str] = None
    deadline: Optional[date] = None  # NOT part of identity
    deadline_note: Optional[str] = None  # e.g. "23:59 Finland time"
    start_date: Optional[str] = None  # free text as stated on the page
    # Structured start/degree-timing facts, set only when the official text
    # supports them (None = not stated/unknown, never guessed):
    start_date_value: Optional[date] = None
    start_date_negotiable: Optional[bool] = None
    completed_degree_required_before_start: Optional[bool] = None
    posted_date: Optional[date] = None  # part of fallback fingerprint
    position_type: Literal[
        "phd", "postdoc", "project_researcher", "research_assistant", "other"
    ] = "other"
    funding: Optional[str] = None
    salary_text: Optional[str] = None
    duration_text: Optional[str] = None
    location: Optional[str] = None
    language_requirements: list[str] = Field(default_factory=list)
    # Nationality/export-control restrictions are an OPPORTUNITY-level official
    # fact, not a global assumption:
    #   none_stated — the posting states no such restriction
    #   stated      — the posting explicitly states a restriction
    #   ambiguous   — the posting hints at possible restrictions unclearly
    nationality_restrictions_status: Literal[
        "none_stated", "stated", "ambiguous"
    ] = "none_stated"
    nationality_restrictions_text: Optional[str] = None
    # Mobility/residence-history rules (e.g. MSCA-style "must not have resided
    # in X for more than N months") are a SEPARATE condition from
    # nationality/export-control restrictions and are recorded separately.
    mobility_requirement_status: Literal[
        "none_stated", "stated", "ambiguous"
    ] = "none_stated"
    mobility_requirement_text: Optional[str] = None
    status: Literal["open", "closed", "expired", "unknown"] = "unknown"
    description_text: str = ""


class OpportunityAI(BaseModel):
    """AI analysis layer. NO fact fields (deadline/salary/status) by design.

    `funding_assessment` and `recommendation` are AI-level interpretation and
    advice only — official funding/status facts live in official.* and a
    recommendation here never finalizes a Decision (apply is never
    auto-finalized).
    """

    model_config = ConfigDict(extra="forbid")

    summary: str
    fit_type: Literal["exact-fit", "adjacent-methodological-fit", "poor-fit"]
    thematic_fit: ScoreWithRationale
    methodological_fit: ScoreWithRationale
    growth_value: ScoreWithRationale
    strategic_value: ScoreWithRationale
    required_skills: list[str] = Field(default_factory=list)  # taxonomy ids
    preferred_skills: list[str] = Field(default_factory=list)  # taxonomy ids
    # taxonomy id -> short verbatim quote from the official text that
    # evidences the skill extraction (required or preferred).
    skill_evidence: dict[str, str] = Field(default_factory=dict)
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    transferable_strengths: list[str] = Field(default_factory=list)
    eligibility_flags: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    # THREE SEPARATE JUDGMENTS: the vacancy decision (recommendation), the
    # research alignment (fit scores/fit_type), and the future value of the
    # lab/group (below). A vacancy can be rejected for timing while the group
    # remains a high-value future target.
    rejection_reasons: list[RejectionReason] = Field(default_factory=list)
    future_group_value: Optional[Literal["high", "medium", "low"]] = None
    future_group_rationale: Optional[str] = None
    funding_assessment: Optional[str] = None  # interpretation, never a fact
    recommendation: Optional[
        Literal["apply", "consider", "monitor", "reject"]
    ] = None
    next_action: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)
    model: str
    prompt_version: str
    analysis_provider: str = "api"  # e.g. "interactive_claude"
    analysis_mode: Literal["automated", "manual_assisted"] = "automated"
    analysis_status: Literal["provisional", "reviewed", "final"] = "provisional"
    analyzed_at: datetime
    analysis_input_hash: str


class OpportunityDerived(BaseModel):
    model_config = ConfigDict(extra="forbid")

    eligibility_gate: Literal["pass", "uncertain", "fail"] = "uncertain"
    eligibility_reasons: list[str] = Field(default_factory=list)
    fit_overall: Optional[int] = Field(default=None, ge=0, le=100)
    urgency: Literal["urgent", "high", "medium", "low", "none"] = "none"
    days_to_deadline: Optional[int] = None
    needs_review: bool = False
    # Timing/readiness of THIS vacancy relative to the user's expected MSc
    # completion. Separate axis from research fit and eligibility: a high-fit
    # vacancy whose start precedes graduation is still not actionable now.
    timing_assessment: Literal[
        "actionable_now",
        "prepare_for_current_cycle",
        "future_target",
        "timing_mismatch",
        "timing_unknown",
    ] = "timing_unknown"


class OpportunityManual(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notes: str = ""
    tags: list[str] = Field(default_factory=list)
    eligibility_override: Optional[Literal["pass", "uncertain", "fail"]] = None
    priority_override: Optional[Literal["high", "medium", "low"]] = None
    # User's own disposition toward this vacancy (web-editable). The
    # preparing/submitted states come from the linked Application, not here.
    user_status: Optional[
        Literal["saved", "future_target", "considering", "not_applying"]
    ] = None
    hidden: bool = False


class Opportunity(Envelope):
    entity_type: Literal["opportunity"] = "opportunity"
    official: OpportunityOfficial
    ai: Optional[OpportunityAI] = None
    derived: OpportunityDerived = Field(default_factory=OpportunityDerived)
    manual: OpportunityManual = Field(default_factory=OpportunityManual)


# --------------------------------------------------------------------------- #
# Organisation
# --------------------------------------------------------------------------- #

class OrganisationOfficial(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    org_type: Literal["university", "faculty", "lab", "group", "funder", "other"]
    parent_org_id: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    website: Optional[str] = None
    careers_url: Optional[str] = None
    retrieved_at: Optional[datetime] = None
    evidence_ids: list[str] = Field(default_factory=list)


class OrganisationAI(BaseModel):
    model_config = ConfigDict(extra="forbid")

    research_themes: list[str] = Field(default_factory=list)
    relevance_summary: str = ""
    confidence: float = Field(ge=0.0, le=1.0)
    model: str
    prompt_version: str
    analyzed_at: datetime
    analysis_input_hash: str


class OrganisationManual(BaseModel):
    model_config = ConfigDict(extra="forbid")

    priority: Optional[Literal["high", "medium", "low"]] = None
    target: bool = False  # member of the target map
    notes: str = ""


class Organisation(Envelope):
    entity_type: Literal["organisation"] = "organisation"
    official: OrganisationOfficial
    ai: Optional[OrganisationAI] = None
    manual: OrganisationManual = Field(default_factory=OrganisationManual)


# --------------------------------------------------------------------------- #
# Person
# --------------------------------------------------------------------------- #

class PersonOfficial(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    org_id: Optional[str] = None
    title: Optional[str] = None
    profile_url: Optional[str] = None
    scholar_url: Optional[str] = None
    email: Optional[str] = None
    retrieved_at: Optional[datetime] = None
    evidence_ids: list[str] = Field(default_factory=list)


class PersonAI(BaseModel):
    model_config = ConfigDict(extra="forbid")

    research_topics: list[str] = Field(default_factory=list)
    recent_work_summary: str = ""
    alignment_notes: str = ""
    confidence: float = Field(ge=0.0, le=1.0)
    model: str
    prompt_version: str
    analyzed_at: datetime
    analysis_input_hash: str


class PersonManual(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contact_status: Literal[
        "not_contacted", "drafted", "contacted", "replied", "meeting", "dormant"
    ] = "not_contacted"
    priority: Optional[Literal["high", "medium", "low"]] = None
    last_check: Optional[date] = None
    notes: str = ""


class Person(Envelope):
    entity_type: Literal["person"] = "person"
    official: PersonOfficial
    ai: Optional[PersonAI] = None
    manual: PersonManual = Field(default_factory=PersonManual)


# --------------------------------------------------------------------------- #
# Signal
# --------------------------------------------------------------------------- #

class SignalOfficial(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signal_type: Literal["paper", "funding", "lab_news", "vacancy_change", "other"]
    title: str
    url: Optional[str] = None
    published_at: Optional[date] = None
    source: str = "manual"
    org_id: Optional[str] = None
    person_ids: list[str] = Field(default_factory=list)
    excerpt: str = ""
    retrieved_at: Optional[datetime] = None
    extracted_content_hash: Optional[str] = None
    evidence_ids: list[str] = Field(default_factory=list)


class SignalAI(BaseModel):
    """Interpretation layer for signals. Generic XR activity is never a
    strong signal by itself — recruitment_likelihood must be justified by
    methodological alignment with the target identity (rationale)."""

    model_config = ConfigDict(extra="forbid")

    relevance_score: int = Field(ge=0, le=100)
    strength: Literal["high", "medium", "low"]
    implications: str = ""
    possible_future_recruitment: Optional[bool] = None
    recruitment_likelihood: Optional[Literal["low", "moderate", "high"]] = None
    recruitment_rationale: str = ""
    risks: list[str] = Field(default_factory=list)
    related_opportunity_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    model: str
    prompt_version: str
    analysis_provider: str = "api"
    analysis_mode: Literal["automated", "manual_assisted"] = "automated"
    analysis_status: Literal["provisional", "reviewed", "final"] = "provisional"
    analyzed_at: datetime
    analysis_input_hash: str


class SignalManual(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dismissed: bool = False
    notes: str = ""


class Signal(Envelope):
    entity_type: Literal["signal"] = "signal"
    official: SignalOfficial
    ai: Optional[SignalAI] = None
    manual: SignalManual = Field(default_factory=SignalManual)


# --------------------------------------------------------------------------- #
# Decision
# --------------------------------------------------------------------------- #

DecisionValue = Literal["apply", "consider", "monitor", "reject"]


class DecisionBasis(BaseModel):
    """Snapshot of the evidence at proposal time."""

    model_config = ConfigDict(extra="forbid")

    eligibility_gate: Literal["pass", "uncertain", "fail"]
    fit_overall: Optional[int] = None
    thematic: Optional[int] = None
    methodological: Optional[int] = None
    growth: Optional[int] = None
    strategic: Optional[int] = None
    confidence: Optional[float] = None


class DecisionSystem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    opportunity_id: str
    proposed: DecisionValue
    proposed_by: Literal["rules", "ai"]
    proposed_at: datetime
    basis: DecisionBasis
    auto_finalized: bool = False

    @model_validator(mode="after")
    def _apply_never_auto_finalized(self) -> "DecisionSystem":
        if self.proposed == "apply" and self.auto_finalized:
            raise ValueError("decision 'apply' can never be auto-finalized")
        return self


class DecisionOutcome(BaseModel):
    """Retrospective: was the proposal right? Lets the system learn."""

    model_config = ConfigDict(extra="forbid")

    result: Optional[Literal["validated", "overturned", "expired"]] = None
    noted_at: Optional[datetime] = None
    note: str = ""


class DecisionManual(BaseModel):
    model_config = ConfigDict(extra="forbid")

    final: Optional[DecisionValue] = None
    decided_at: Optional[datetime] = None
    rationale: str = ""
    rejection_reasons: list[RejectionReason] = Field(default_factory=list)
    superseded_by: Optional[str] = None


class Decision(Envelope):
    entity_type: Literal["decision"] = "decision"
    system: DecisionSystem
    manual: DecisionManual = Field(default_factory=DecisionManual)
    outcome: DecisionOutcome = Field(default_factory=DecisionOutcome)


# --------------------------------------------------------------------------- #
# Action
# --------------------------------------------------------------------------- #

class ActionRelated(BaseModel):
    model_config = ConfigDict(extra="forbid")

    opportunity_id: Optional[str] = None
    person_id: Optional[str] = None
    application_id: Optional[str] = None


class ActionSystem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_type: Literal["research", "outreach", "application", "skill", "admin"]
    related: ActionRelated = Field(default_factory=ActionRelated)
    created_by: Literal["ai", "rules", "human"]
    due_date: Optional[date] = None
    priority: Literal["high", "medium", "low"] = "medium"
    recommended_reason: Optional[str] = None  # when AI-suggested
    model: Optional[str] = None
    prompt_version: Optional[str] = None


class ActionOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result: Optional[
        Literal["completed", "dropped", "no_response", "superseded"]
    ] = None
    completed_at: Optional[datetime] = None
    note: str = ""


class ActionManual(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    status: Literal["todo", "doing", "done", "dropped"] = "todo"
    notes: str = ""


class Action(Envelope):
    entity_type: Literal["action"] = "action"
    system: ActionSystem
    manual: ActionManual
    outcome: ActionOutcome = Field(default_factory=ActionOutcome)


# --------------------------------------------------------------------------- #
# Application
# --------------------------------------------------------------------------- #

class ApplicationMaterial(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    status: Literal["todo", "draft", "final"] = "todo"
    path: Optional[str] = None


class ApplicationEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ts: datetime
    event: str
    note: str = ""


class ApplicationOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result: Optional[
        Literal[
            "offer",
            "interview_then_reject",
            "rejected",
            "withdrawn",
            "no_response",
        ]
    ] = None
    decided_at: Optional[datetime] = None
    feedback_note: str = ""


class ApplicationManual(BaseModel):
    """Applications are human-driven by design.

    'identified' is the pre-decision tracking state: the record exists so the
    opportunity is tracked, but no application decision has been made."""

    model_config = ConfigDict(extra="forbid")

    stage: Literal[
        "identified",
        "preparing",
        "submitted",
        "monitoring",
        "awaiting_response",
        "interview",
        "offered",
        "rejected",
        "withdrawn",
    ] = "identified"
    submitted_at: Optional[date] = None
    portal_reference: Optional[str] = None  # optional confirmation/reference id
    documents_used: list[str] = Field(default_factory=list)  # versions at submission
    materials: list[ApplicationMaterial] = Field(default_factory=list)
    contact_person_ids: list[str] = Field(default_factory=list)
    events: list[ApplicationEvent] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    next_step: str = ""
    next_step_due: Optional[date] = None
    internal_due_date: Optional[date] = None  # self-imposed prep deadline
    notes: str = ""


class ApplicationSystem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    opportunity_id: str


class Application(Envelope):
    entity_type: Literal["application"] = "application"
    system: ApplicationSystem
    manual: ApplicationManual = Field(default_factory=ApplicationManual)
    outcome: ApplicationOutcome = Field(default_factory=ApplicationOutcome)


# --------------------------------------------------------------------------- #
# SkillProgress (S8b): the audited, human-owned per-skill state that changes as
# the user learns. The stable baseline stays in config/current_profile.yaml; the
# effective profile is baseline + SkillProgress. Web edits go here (manual only),
# never into current_profile.yaml.

SkillLevel = Literal["none", "beginner", "intermediate", "advanced"]
LearningStatus = Literal[
    "not_started", "learning", "practicing", "proficient", "paused"
]


class SkillProgressManual(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_level: Optional[SkillLevel] = None       # overrides the baseline level
    learning_status: Optional[LearningStatus] = None
    confidence: Optional[Literal["low", "medium", "high"]] = None
    target_level: Optional[SkillLevel] = None         # where the user wants to get to
    evidence: str = ""
    notes: str = ""


class SkillProgressSystem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skill_id: str                                     # taxonomy id this tracks


class SkillProgress(Envelope):
    entity_type: Literal["skill_progress"] = "skill_progress"
    system: SkillProgressSystem
    manual: SkillProgressManual = Field(default_factory=SkillProgressManual)


# --------------------------------------------------------------------------- #

ENTITY_MODELS: dict[str, type[Envelope]] = {
    "opportunity": Opportunity,
    "organisation": Organisation,
    "person": Person,
    "signal": Signal,
    "decision": Decision,
    "action": Action,
    "application": Application,
    "skill_progress": SkillProgress,
}

# Canonical subdirectory per entity type.
ENTITY_DIRS = {
    "opportunity": "opportunities",
    "organisation": "organisations",
    "person": "people",
    "signal": "signals",
    "decision": "decisions",
    "action": "actions",
    "application": "applications",
    "skill_progress": "skill_progress",
}
