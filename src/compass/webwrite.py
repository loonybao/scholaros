"""Safe web write layer (S8a).

The web UI may write ONLY manual-layer fields, Application records, Action
records, and user notes. Request models forbid extra fields, so official/ai/
derived data can never be smuggled in. Every write goes through store.py
(actor="user", atomic + locked, field-level change_history), rejects stale
concurrent updates (optimistic concurrency on updated_at), avoids no-op
history, and refreshes the SQLite index + vault/generated. vault/notes is never
touched.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .config import Config
from .models import (
    Action, ActionManual, ActionRelated, ActionSystem,
    Application, ApplicationManual, ApplicationMaterial, ApplicationSystem,
)
from .rules import valid_application_transition
from .store import Store
from .views import refresh_all


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
    correction: bool = False                    # allow a non-forward stage change
    correction_note: Optional[str] = None
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


# ------------------------------------------------------------------- writes #

def create_application(cfg: Config, store: Store, opp_id: str) -> dict:
    if not store.exists("opportunity", opp_id):
        raise NotFound(f"unknown opportunity {opp_id}")
    for app in store.load_all("application"):
        if app.system.opportunity_id == opp_id:
            raise Conflict(f"an application already exists for {opp_id} ({app.id})")
    # new_id() adds the "app_" prefix; strip "opp_" so the slug isn't doubled.
    app = Application(
        id=store.new_id("application", opp_id.replace("opp_", "", 1)),
        system=ApplicationSystem(opportunity_id=opp_id),
        manual=ApplicationManual(stage="identified"),
    )
    store.save(app, actor="user", note="application created from opportunity")
    refresh_all(cfg, store)
    return {"id": app.id, "stage": app.manual.stage}


def patch_opportunity_manual(cfg: Config, store: Store, opp_id: str,
                             patch: OppManualPatch) -> dict:
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
    saved = store.save(opp, actor="user", note="manual annotation updated")
    refresh_all(cfg, store)
    return {"id": saved.id, "user_status": saved.manual.user_status,
            "updated_at": saved.updated_at.isoformat()}


def patch_application(cfg: Config, store: Store, app_id: str, patch: AppPatch) -> dict:
    if not store.exists("application", app_id):
        raise NotFound(f"unknown application {app_id}")
    app = store.load("application", app_id)
    _check_version(app, patch.expected_updated_at)
    m = app.manual

    if patch.stage is not None and patch.stage != m.stage:
        if not patch.correction and not valid_application_transition(m.stage, patch.stage):
            raise InvalidTransition(
                f"{m.stage} -> {patch.stage} is not a permitted transition; "
                f"use a correction to override.")
        if patch.stage == "submitted" and not patch.correction:
            if not patch.confirm_submitted or patch.submitted_at is None:
                raise WriteError(
                    "marking submitted requires submitted_at and confirmation")
        note = (f"correction: {patch.correction_note}" if patch.correction
                else f"stage {m.stage} -> {patch.stage}")
        m.stage = patch.stage
        m.events.append(_event(f"stage:{patch.stage}", patch.correction_note or ""))
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
        m.materials = [ApplicationMaterial(name=x.name, status=x.status, path=x.path)
                       for x in patch.materials]
    if patch.submitted_at is not None:
        m.submitted_at = patch.submitted_at
    if patch.portal_reference is not None:
        m.portal_reference = patch.portal_reference
    if patch.documents_used is not None:
        m.documents_used = patch.documents_used

    saved = store.save(app, actor="user", note=note)
    refresh_all(cfg, store)
    return {"id": saved.id, "stage": saved.manual.stage,
            "updated_at": saved.updated_at.isoformat()}


def create_action(cfg: Config, store: Store, req: ActionCreate) -> dict:
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
    store.save(act, actor="user", note="action created via web")
    refresh_all(cfg, store)
    return {"id": act.id}


def report_data_issue(cfg: Config, store: Store, req: DataIssue) -> dict:
    """Official data errors are NEVER edited in place — they become an action
    for human review."""
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
    store.save(act, actor="user", note="data issue reported for review")
    refresh_all(cfg, store)
    return {"id": act.id}


def _event(event: str, note: str):
    from .models import ApplicationEvent
    return ApplicationEvent(ts=datetime.now(timezone.utc), event=event, note=note)
