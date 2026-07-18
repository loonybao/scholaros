"""Safe web write layer (S8a / S8a.1).

The web UI may write ONLY manual-layer fields, Application records, Action
records, and user notes. Request models forbid extra fields, so official/ai/
derived data can never be smuggled in. Every write goes through store.py
(actor="user", atomic + locked, field-level change_history), rejects stale
concurrent updates (optimistic concurrency on updated_at), avoids no-op
history, and then refreshes ONLY the affected entity (its SQLite row + its one
generated page) via views.try_refresh — never a full recompute/rebuild/export.

Stage handling: forward transitions follow rules.valid_application_transition;
marking submitted requires a date + explicit confirmation; a submitted
application can only be reopened through the dedicated, audited
correct_submission flow (never a silent PATCH). vault/notes is never touched.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict

from .config import Config
from .models import (
    Action, ActionManual, ActionRelated, ActionSystem,
    Application, ApplicationEvent, ApplicationManual, ApplicationMaterial,
    ApplicationSystem, SkillProgress, SkillProgressManual, SkillProgressSystem,
)
from .perf import Timings
from .rules import valid_application_transition
from .store import Store
from .views import try_refresh


# ------------------------------------------------------------------ errors #

class WriteError(Exception):
    status = 400


class NotFound(WriteError):
    status = 404


class StaleWrite(WriteError):
    status = 409


class Conflict(WriteError):
    status = 409


class InvalidTransition(WriteError):
    status = 422


def _check_version(entity, expected: Optional[str]) -> None:
    """Optimistic concurrency: reject a write based on a stale snapshot."""
    if expected is None:
        return
    current = entity.updated_at.isoformat() if entity.updated_at else None
    if current != expected:
        raise StaleWrite(
            "This record changed since you loaded it; reload and retry.")


def _event(event: str, note: str = "") -> ApplicationEvent:
    return ApplicationEvent(ts=datetime.now(timezone.utc), event=event, note=note)


# ------------------------------------------------------------ request models #

class OppManualPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_updated_at: Optional[str] = None
    user_status: Optional[str] = None          # saved/future_target/considering/not_applying/null
    notes: Optional[str] = None
    clear_user_status: bool = False


class MaterialInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    status: str = "todo"                        # todo/draft/final
    path: Optional[str] = None


class AppPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_updated_at: Optional[str] = None
    stage: Optional[str] = None
    internal_due_date: Optional[date] = None
    next_step: Optional[str] = None
    next_step_due: Optional[date] = None
    notes: Optional[str] = None
    blockers: Optional[list[str]] = None
    materials: Optional[list[MaterialInput]] = None
    # Submission (required together when moving to submitted):
    submitted_at: Optional[date] = None
    confirm_submitted: bool = False
    portal_reference: Optional[str] = None
    documents_used: Optional[list[str]] = None


class OutcomePatch(BaseModel):
    """Record how an application resolved + a reflection note (the learning
    loop). decided_at is stamped server-side when a result is set."""
    model_config = ConfigDict(extra="forbid")
    expected_updated_at: Optional[str] = None
    result: Optional[str] = None       # offer/interview_then_reject/rejected/withdrawn/no_response
    feedback_note: Optional[str] = None


class SubmissionCorrection(BaseModel):
    """Dedicated, audited reopen of a submitted application. Not a generic
    stage change — the normal PATCH route cannot perform submitted -> preparing."""
    model_config = ConfigDict(extra="forbid")
    expected_updated_at: Optional[str] = None
    correction_reason: str
    confirm: bool = False


class ActionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    action_type: str = "admin"
    priority: str = "medium"
    due_date: Optional[date] = None
    opportunity_id: Optional[str] = None
    person_id: Optional[str] = None
    application_id: Optional[str] = None
    notes: str = ""


class DataIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    opportunity_id: str
    field: str
    description: str


class SkillProgressPatch(BaseModel):
    """Human-owned skill progress (S8b). Writes a canonical SkillProgress entity
    (baseline current_profile.yaml is never touched). A null field leaves the
    stored value; use clear=true to reset a field to the baseline."""
    model_config = ConfigDict(extra="forbid")
    expected_updated_at: Optional[str] = None
    current_level: Optional[str] = None
    learning_status: Optional[str] = None
    confidence: Optional[str] = None
    target_level: Optional[str] = None
    evidence: Optional[str] = None
    notes: Optional[str] = None


# ------------------------------------------------------------------- writes #

def create_application(cfg: Config, store: Store, opp_id: str) -> dict:
    tm = Timings("create_application")
    if not store.exists("opportunity", opp_id):
        raise NotFound(f"unknown opportunity {opp_id}")
    for app in store.load_all("application"):
        if app.system.opportunity_id == opp_id:
            raise Conflict(f"an application already exists for {opp_id} ({app.id})")
    # new_id() adds the "app_" prefix; strip "opp_" so the slug isn't doubled.
    app = Application(
        id=store.new_id("application", opp_id.replace("opp_", "", 1)),
        system=ApplicationSystem(opportunity_id=opp_id),
        manual=ApplicationManual(stage="identified", events=[_event("created")]),
    )
    with tm.measure("save"):
        store.save(app, actor="user", note="application created from opportunity")
    warning = try_refresh(cfg, store, "application", app.id, tm)
    tm.report()
    return {"id": app.id, "stage": app.manual.stage, "warning": warning}


def patch_opportunity_manual(cfg: Config, store: Store, opp_id: str,
                             patch: OppManualPatch) -> dict:
    tm = Timings("patch_opportunity_manual")
    if not store.exists("opportunity", opp_id):
        raise NotFound(f"unknown opportunity {opp_id}")
    opp = store.load("opportunity", opp_id)
    _check_version(opp, patch.expected_updated_at)
    if patch.clear_user_status:
        opp.manual.user_status = None
    elif patch.user_status is not None:
        opp.manual.user_status = patch.user_status
    if patch.notes is not None:
        opp.manual.notes = patch.notes
    with tm.measure("save"):
        saved = store.save(opp, actor="user", note="manual annotation updated")
    warning = try_refresh(cfg, store, "opportunity", opp_id, tm)
    tm.report()
    return {"id": saved.id, "user_status": saved.manual.user_status,
            "updated_at": saved.updated_at.isoformat(), "warning": warning}


def patch_application(cfg: Config, store: Store, app_id: str, patch: AppPatch) -> dict:
    tm = Timings("patch_application")
    if not store.exists("application", app_id):
        raise NotFound(f"unknown application {app_id}")
    app = store.load("application", app_id)
    _check_version(app, patch.expected_updated_at)
    m = app.manual

    if patch.stage is not None and patch.stage != m.stage:
        if m.stage == "submitted" and patch.stage == "preparing":
            raise InvalidTransition(
                "use the submission-correction action to reopen a submitted "
                "application, so the correction is recorded with a reason.")
        if not valid_application_transition(m.stage, patch.stage):
            raise InvalidTransition(
                f"{m.stage} -> {patch.stage} is not a permitted transition.")
        if patch.stage == "submitted":
            if not patch.confirm_submitted or patch.submitted_at is None:
                raise WriteError(
                    "marking submitted requires submitted_at and confirmation")
            m.events.append(_event("submitted", patch.submitted_at.isoformat()))
        elif patch.stage == "preparing":
            m.events.append(_event("preparing"))
        else:
            m.events.append(_event("stage", patch.stage))
        note = f"stage {m.stage} -> {patch.stage}"
        m.stage = patch.stage
    else:
        note = "application updated"

    if patch.internal_due_date is not None:
        m.internal_due_date = patch.internal_due_date
    if patch.next_step is not None:
        m.next_step = patch.next_step
    if patch.next_step_due is not None:
        m.next_step_due = patch.next_step_due
    if patch.notes is not None:
        m.notes = patch.notes
    if patch.blockers is not None:
        m.blockers = patch.blockers
    if patch.materials is not None:
        new_materials = [ApplicationMaterial(name=x.name, status=x.status, path=x.path)
                         for x in patch.materials]
        if new_materials != m.materials:
            done = sum(1 for x in new_materials if x.status == "final")
            m.events.append(_event("checklist", f"{done}/{len(new_materials)}"))
        m.materials = new_materials
    if patch.submitted_at is not None:
        m.submitted_at = patch.submitted_at
    if patch.portal_reference is not None:
        m.portal_reference = patch.portal_reference
    if patch.documents_used is not None:
        m.documents_used = patch.documents_used

    with tm.measure("save"):
        saved = store.save(app, actor="user", note=note)
    warning = try_refresh(cfg, store, "application", app_id, tm)
    tm.report()
    return {"id": saved.id, "stage": saved.manual.stage,
            "updated_at": saved.updated_at.isoformat(), "warning": warning}


def correct_submission(cfg: Config, store: Store, app_id: str,
                       req: SubmissionCorrection) -> dict:
    """Audited submitted -> preparing. Requires a reason and confirmation;
    clears submission-only fields but preserves the original submission event
    and the reason in the change history."""
    tm = Timings("correct_submission")
    if not store.exists("application", app_id):
        raise NotFound(f"unknown application {app_id}")
    app = store.load("application", app_id)
    _check_version(app, req.expected_updated_at)
    m = app.manual
    if m.stage != "submitted":
        raise InvalidTransition(
            "only a submitted application can have its submission corrected.")
    reason = (req.correction_reason or "").strip()
    if not reason or not req.confirm:
        raise WriteError(
            "a correction requires a reason and explicit confirmation.")

    prior = [f"was submitted {m.submitted_at}"]
    if m.portal_reference:
        prior.append(f"ref {m.portal_reference}")
    if m.documents_used:
        prior.append("docs: " + ", ".join(m.documents_used))
    m.events.append(_event("corrected", f"{reason} — ({'; '.join(prior)})"))
    m.stage = "preparing"
    m.submitted_at = None
    m.portal_reference = None
    m.documents_used = []

    with tm.measure("save"):
        saved = store.save(app, actor="user",
                           note=f"submission corrected to preparing: {reason}")
    warning = try_refresh(cfg, store, "application", app_id, tm)
    tm.report()
    return {"id": saved.id, "stage": saved.manual.stage,
            "updated_at": saved.updated_at.isoformat(), "warning": warning}


def record_outcome(cfg: Config, store: Store, app_id: str, patch: OutcomePatch) -> dict:
    """Record an application's result + feedback (human-owned outcome layer)."""
    tm = Timings("record_outcome")
    if not store.exists("application", app_id):
        raise NotFound(f"unknown application {app_id}")
    app = store.load("application", app_id)
    _check_version(app, patch.expected_updated_at)
    if patch.result is not None:
        app.outcome.result = patch.result
        app.outcome.decided_at = datetime.now(timezone.utc)
    if patch.feedback_note is not None:
        app.outcome.feedback_note = patch.feedback_note
    with tm.measure("save"):
        saved = store.save(app, actor="user", note="outcome recorded")
    warning = try_refresh(cfg, store, "application", app_id, tm)
    tm.report()
    return {"id": saved.id, "result": saved.outcome.result,
            "updated_at": saved.updated_at.isoformat(), "warning": warning}


def create_action(cfg: Config, store: Store, req: ActionCreate) -> dict:
    tm = Timings("create_action")
    act = Action(
        id=store.new_id("action", req.title),
        system=ActionSystem(
            action_type=req.action_type, priority=req.priority,
            due_date=req.due_date, created_by="human",
            related=ActionRelated(opportunity_id=req.opportunity_id,
                                  person_id=req.person_id,
                                  application_id=req.application_id),
        ),
        manual=ActionManual(title=req.title, status="todo", notes=req.notes),
    )
    with tm.measure("save"):
        store.save(act, actor="user", note="action created via web")
    warning = try_refresh(cfg, store, "action", act.id, tm)
    tm.report()
    return {"id": act.id, "warning": warning}


def set_skill_progress(cfg: Config, store: Store, skill_id: str,
                       patch: SkillProgressPatch) -> dict:
    """Create or update the SkillProgress for one taxonomy skill (manual only).
    The stable baseline in current_profile.yaml is never modified."""
    tm = Timings("set_skill_progress")
    if skill_id not in cfg.taxonomy_ids():
        raise WriteError(f"unknown skill '{skill_id}'")
    sp_id = f"skp_{skill_id}"
    if store.exists("skill_progress", sp_id):
        sp = store.load("skill_progress", sp_id)
    else:
        sp = SkillProgress(id=sp_id, system=SkillProgressSystem(skill_id=skill_id),
                           manual=SkillProgressManual())
    _check_version(sp, patch.expected_updated_at)
    m = sp.manual
    for field in ("current_level", "learning_status", "confidence",
                  "target_level", "evidence", "notes"):
        val = getattr(patch, field)
        if val is not None:
            setattr(m, field, val)
    with tm.measure("save"):
        saved = store.save(sp, actor="user", note="skill progress updated")
    warning = try_refresh(cfg, store, "skill_progress", sp_id, tm)
    tm.report()
    return {"id": saved.id, "skill_id": skill_id,
            "updated_at": saved.updated_at.isoformat(), "warning": warning}


def report_data_issue(cfg: Config, store: Store, req: DataIssue) -> dict:
    """Official data errors are NEVER edited in place — they become an action
    for human review."""
    tm = Timings("report_data_issue")
    if not store.exists("opportunity", req.opportunity_id):
        raise NotFound(f"unknown opportunity {req.opportunity_id}")
    act = Action(
        id=store.new_id("action", f"data-issue-{req.opportunity_id}-{req.field}"),
        system=ActionSystem(
            action_type="admin", priority="medium", created_by="human",
            related=ActionRelated(opportunity_id=req.opportunity_id),
        ),
        manual=ActionManual(
            title=f"Review reported data issue: {req.field}",
            status="todo",
            notes=f"Field: {req.field}\nReported: {req.description}\n"
                  f"Verify against the official source before any correction.",
        ),
    )
    with tm.measure("save"):
        store.save(act, actor="user", note="data issue reported for review")
    warning = try_refresh(cfg, store, "action", act.id, tm)
    tm.report()
    return {"id": act.id, "warning": warning}
