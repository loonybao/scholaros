"""SQLite query index — derived from canonical JSON, rebuildable at any time.

Never the source of truth: `rebuild_index` drops and recreates everything from
data/canonical/. The web dashboard reads ONLY through this index (short-lived
connections so rebuilds can run while the server is up).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from .config import Config
from .store import Store

SCHEMA = """
DROP TABLE IF EXISTS opportunities;
DROP TABLE IF EXISTS organisations;
DROP TABLE IF EXISTS people;
DROP TABLE IF EXISTS actions;
DROP TABLE IF EXISTS signals;
DROP TABLE IF EXISTS applications;
DROP TABLE IF EXISTS meta;

CREATE TABLE actions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    priority TEXT NOT NULL,
    due_date TEXT,
    opportunity_id TEXT,
    person_id TEXT
);

CREATE TABLE signals (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    org_id TEXT,
    url TEXT,
    published_at TEXT,
    retrieved_at TEXT,
    excerpt TEXT,
    person_ids TEXT NOT NULL DEFAULT '[]',
    related_opportunity_ids TEXT NOT NULL DEFAULT '[]',
    recruitment_likelihood TEXT,
    recruitment_rationale TEXT,
    risks TEXT NOT NULL DEFAULT '[]',
    confidence REAL,
    dismissed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE applications (
    id TEXT PRIMARY KEY,
    opportunity_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    next_step TEXT,
    next_step_due TEXT,
    internal_due_date TEXT,
    blockers TEXT NOT NULL DEFAULT '[]',
    notes TEXT,
    materials TEXT NOT NULL DEFAULT '[]',
    submitted_at TEXT,
    portal_reference TEXT,
    documents_used TEXT NOT NULL DEFAULT '[]',
    events TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT
);

CREATE TABLE organisations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    org_type TEXT NOT NULL,
    country TEXT,
    parent_org_id TEXT,
    target INTEGER NOT NULL DEFAULT 0,
    priority TEXT,
    notes TEXT
);

CREATE TABLE opportunities (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    org_id TEXT NOT NULL,
    lab_org_id TEXT,
    canonical_url TEXT NOT NULL,
    deadline TEXT,
    days_to_deadline INTEGER,
    urgency TEXT NOT NULL,
    eligibility_gate TEXT NOT NULL,
    eligibility_reasons TEXT NOT NULL,  -- JSON array
    fit_overall INTEGER,
    fit_type TEXT,
    recommendation TEXT,
    analysis_status TEXT,
    methodological_fit INTEGER,
    required_skills TEXT NOT NULL DEFAULT '[]',   -- JSON array of taxonomy ids
    preferred_skills TEXT NOT NULL DEFAULT '[]',  -- JSON array of taxonomy ids
    rejection_reasons TEXT NOT NULL DEFAULT '[]', -- JSON array (enum)
    future_group_value TEXT,
    status TEXT NOT NULL,
    position_type TEXT NOT NULL,
    location TEXT,
    salary_text TEXT,
    needs_review INTEGER NOT NULL DEFAULT 0,
    hidden INTEGER NOT NULL DEFAULT 0,
    analyzed INTEGER NOT NULL DEFAULT 0,
    analysis_stale INTEGER NOT NULL DEFAULT 0,
    retrieved_at TEXT,
    timing_assessment TEXT NOT NULL DEFAULT 'timing_unknown',
    user_status TEXT,
    updated_at TEXT
);

CREATE TABLE people (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    org_id TEXT,
    title TEXT,
    contact_status TEXT NOT NULL,
    priority TEXT
);

CREATE TABLE meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def index_path(cfg: Config) -> Path:
    return cfg.paths.index / "compass.sqlite"


def connect(cfg: Config) -> sqlite3.Connection:
    conn = sqlite3.connect(index_path(cfg))
    conn.row_factory = sqlite3.Row
    return conn


def rebuild_index(cfg: Config, store: Store) -> int:
    """Drop and rebuild the whole index from canonical. Returns row count."""
    cfg.paths.index.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(index_path(cfg))
    rows = 0
    try:
        conn.executescript(SCHEMA)

        for org in store.load_all("organisation"):
            conn.execute(
                "INSERT INTO organisations VALUES (?,?,?,?,?,?,?,?)",
                (
                    org.id,
                    org.official.name,
                    org.official.org_type,
                    org.official.country,
                    org.official.parent_org_id,
                    int(org.manual.target),
                    org.manual.priority,
                    org.manual.notes,
                ),
            )
            rows += 1

        for opp in store.load_all("opportunity"):
            _insert(conn, "opportunities", _opportunity_values(cfg, opp))
            rows += 1

        for act in store.load_all("action"):
            _insert(conn, "actions", _action_values(act))
            rows += 1

        for sig in store.load_all("signal"):
            conn.execute(
                "INSERT INTO signals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    sig.id,
                    sig.official.title,
                    sig.official.signal_type,
                    sig.official.org_id,
                    sig.official.url,
                    sig.official.published_at.isoformat()
                    if sig.official.published_at else None,
                    sig.official.retrieved_at.isoformat()
                    if sig.official.retrieved_at else None,
                    sig.official.excerpt,
                    json.dumps(sig.official.person_ids),
                    json.dumps(sig.ai.related_opportunity_ids if sig.ai else []),
                    sig.ai.recruitment_likelihood if sig.ai else None,
                    sig.ai.recruitment_rationale if sig.ai else None,
                    json.dumps(sig.ai.risks if sig.ai else [], ensure_ascii=False),
                    sig.ai.confidence if sig.ai else None,
                    int(sig.manual.dismissed),
                ),
            )
            rows += 1

        for app in store.load_all("application"):
            _insert(conn, "applications", _application_values(app))
            rows += 1

        for per in store.load_all("person"):
            conn.execute(
                "INSERT INTO people VALUES (?,?,?,?,?,?)",
                (
                    per.id,
                    per.official.name,
                    per.official.org_id,
                    per.official.title,
                    per.manual.contact_status,
                    per.manual.priority,
                ),
            )
            rows += 1

        counts = {
            etype: sum(1 for _ in store.load_all(etype))
            for etype in ("opportunity", "organisation", "person", "signal",
                          "decision", "action", "application")
        }
        conn.execute(
            "INSERT INTO meta VALUES ('entity_counts', ?)", (json.dumps(counts),)
        )
        conn.execute(
            "INSERT INTO meta VALUES ('rebuilt_at', ?)",
            (datetime.now(timezone.utc).isoformat(),),
        )
        conn.commit()
    finally:
        conn.close()
    return rows


# ---------------------------------------------------- row builders + upsert #
# One builder per table, shared by the full rebuild and the incremental
# upserts, so an incremental write produces byte-identical rows to a full
# rebuild (guaranteed by test_s8a1). Ordinary user writes touch a single row
# instead of dropping and rebuilding every table.

def _insert(conn: sqlite3.Connection, table: str, values: tuple) -> None:
    ph = "(" + ",".join(["?"] * len(values)) + ")"
    conn.execute(f"INSERT OR REPLACE INTO {table} VALUES {ph}", values)


def _opportunity_values(cfg: Config, opp) -> tuple:
    from .analysis_io import analysis_input_hash
    from .rules import effective_recommendation
    o, d = opp.official, opp.derived
    stale = bool(
        opp.ai is not None
        and opp.ai.analysis_input_hash != analysis_input_hash(cfg, opp)
    )
    return (
        opp.id, o.title, o.org_id, o.lab_org_id, o.canonical_url,
        o.deadline.isoformat() if o.deadline else None,
        d.days_to_deadline, d.urgency, d.eligibility_gate,
        json.dumps(d.eligibility_reasons, ensure_ascii=False), d.fit_overall,
        opp.ai.fit_type if opp.ai else None,
        effective_recommendation(d.eligibility_gate,
                                 opp.ai.recommendation if opp.ai else None),
        opp.ai.analysis_status if opp.ai else None,
        opp.ai.methodological_fit.score if opp.ai else None,
        json.dumps(opp.ai.required_skills if opp.ai else []),
        json.dumps(opp.ai.preferred_skills if opp.ai else []),
        json.dumps(opp.ai.rejection_reasons if opp.ai else []),
        opp.ai.future_group_value if opp.ai else None,
        o.status, o.position_type, o.location, o.salary_text,
        int(d.needs_review), int(opp.manual.hidden), int(opp.ai is not None),
        int(stale), o.retrieved_at.isoformat() if o.retrieved_at else None,
        d.timing_assessment, opp.manual.user_status,
        opp.updated_at.isoformat() if opp.updated_at else None,
    )


def _application_values(app) -> tuple:
    m = app.manual
    return (
        app.id, app.system.opportunity_id, m.stage, m.next_step,
        m.next_step_due.isoformat() if m.next_step_due else None,
        m.internal_due_date.isoformat() if m.internal_due_date else None,
        json.dumps(m.blockers, ensure_ascii=False), m.notes,
        json.dumps([mat.model_dump(mode="json") for mat in m.materials],
                   ensure_ascii=False),
        m.submitted_at.isoformat() if m.submitted_at else None,
        m.portal_reference, json.dumps(m.documents_used, ensure_ascii=False),
        json.dumps([e.model_dump(mode="json") for e in m.events],
                   ensure_ascii=False),
        app.updated_at.isoformat() if app.updated_at else None,
    )


def _action_values(act) -> tuple:
    return (
        act.id, act.manual.title, act.manual.status, act.system.priority,
        act.system.due_date.isoformat() if act.system.due_date else None,
        act.system.related.opportunity_id, act.system.related.person_id,
    )


def _touch_and_count(conn, entity_type: str, table: str) -> None:
    """Refresh rebuilt_at and the single affected entity count. Cheap: one
    COUNT, no full reload."""
    n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    row = conn.execute(
        "SELECT value FROM meta WHERE key='entity_counts'").fetchone()
    counts = json.loads(row[0]) if row else {}
    counts[entity_type] = n
    _insert(conn, "meta", ("entity_counts", json.dumps(counts)))
    _insert(conn, "meta", ("rebuilt_at", datetime.now(timezone.utc).isoformat()))


def upsert_opportunity(cfg: Config, opp) -> None:
    conn = connect(cfg)
    try:
        _insert(conn, "opportunities", _opportunity_values(cfg, opp))
        _touch_and_count(conn, "opportunity", "opportunities")
        conn.commit()
    finally:
        conn.close()


def upsert_application(cfg: Config, app) -> None:
    conn = connect(cfg)
    try:
        _insert(conn, "applications", _application_values(app))
        _touch_and_count(conn, "application", "applications")
        conn.commit()
    finally:
        conn.close()


def upsert_action(cfg: Config, act) -> None:
    conn = connect(cfg)
    try:
        _insert(conn, "actions", _action_values(act))
        _touch_and_count(conn, "action", "actions")
        conn.commit()
    finally:
        conn.close()


# ------------------------------------------------------------------ queries #

def dashboard_data(cfg: Config, today: date) -> dict:
    """One aggregated payload for GET /api/dashboard. Read-only."""
    conn = connect(cfg)
    try:
        opp_sql = """
            SELECT o.*, g.name AS org_name
            FROM opportunities o
            LEFT JOIN organisations g ON g.id = o.org_id
            WHERE o.hidden = 0
        """
        all_opps = [dict(r) for r in conn.execute(opp_sql)]
        for r in all_opps:
            r["eligibility_reasons"] = json.loads(r["eligibility_reasons"])
            r["needs_review"] = bool(r["needs_review"])
            r["analyzed"] = bool(r["analyzed"])

        open_opps = [
            r for r in all_opps
            if r["status"] in ("open", "unknown") and r["eligibility_gate"] != "fail"
        ]
        open_opps.sort(key=lambda r: (r["deadline"] is None, r["deadline"] or ""))

        # Action Required contains ONLY genuinely actionable items:
        #   - apply/consider recommendations whose TIMING is actionable now
        #     (actionable_now / prepare_for_current_cycle), so a high-fit
        #     vacancy that starts before graduation does not push outreach,
        #   - explicit manual-verification tasks (open Action records, added
        #     to the payload below).
        # When no graduation horizon is recorded, the timing gate is not
        # applied (fall back to fit-only). Unanalysed records and stale
        # monitor/reject dispositions go to the Analysis Queue.
        for r in all_opps:
            r["analysis_stale"] = bool(r["analysis_stale"])
        from .rules import graduation_horizon
        horizon = graduation_horizon(cfg.constraints, today)
        actionable_timing = {"actionable_now", "prepare_for_current_cycle"}
        action_required = [
            r for r in open_opps
            if r["recommendation"] in ("apply", "consider")
            and (horizon is None or r["timing_assessment"] in actionable_timing)
        ]

        analysis_queue = [
            r for r in open_opps
            if not r["analyzed"]
            or (r["analysis_stale"] and r["recommendation"] not in ("apply", "consider"))
        ]

        open_tasks = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM actions WHERE status IN ('todo','doing') "
                "ORDER BY due_date IS NULL, due_date"
            )
        ]
        upcoming = [
            r for r in open_opps
            if r["days_to_deadline"] is not None and 0 <= r["days_to_deadline"] <= 45
        ]
        review_queue = [r for r in all_opps if r["needs_review"]]

        meta = {
            row["key"]: json.loads(row["value"])
            if row["key"] == "entity_counts" else row["value"]
            for row in conn.execute("SELECT key, value FROM meta")
        }
    finally:
        conn.close()

    # Signals intelligence panels. Signals NEVER enter action_required —
    # only their concrete time-sensitive user actions (Action records) do.
    feed = signals_feed(cfg)
    watchlist = watchlist_data(cfg)
    prep_actions = [
        {"target": t["name"], "item": i}
        for t in watchlist for i in t["preparation_items"][:3]
    ]

    # Meaningful changes: intelligence worth surfacing (collector failures and
    # verified signals). Heuristic feed, not a per-run diff — kept deliberately
    # small so the homepage shows what changed, not every collected vacancy.
    changes: list[dict] = []
    health_path = cfg.paths.status / "collector_health.json"
    if health_path.is_file():
        with open(health_path, encoding="utf-8") as f:
            collectors = json.load(f)
        for name, info in collectors.items():
            if info.get("consecutive_errors"):
                changes.append({
                    "kind": "collector_issue", "severity": "danger",
                    "source": name, "detail": info.get("last_error"),
                })
    for s in feed[:4]:
        changes.append({
            "kind": "signal", "severity": "info", "title": s["title"],
            "org_name": s.get("org_name"),
            "recruitment_likelihood": s.get("recruitment_likelihood"),
        })
    meaningful_changes = changes[:5]

    # High-fit vacancies that are not actionable now because of the graduation
    # horizon are surfaced separately as market intelligence / future-target
    # evidence — never dropped, never pushed as an action.
    future_target_intel = [
        r for r in open_opps
        if r["recommendation"] in ("apply", "consider")
        and r["timing_assessment"] not in actionable_timing
    ] if horizon else []

    return {
        "generated_at": today.isoformat(),
        "graduation_horizon": horizon,
        "action_required": action_required,
        "future_target_intel": future_target_intel,
        "manual_tasks": open_tasks,
        "analysis_queue": analysis_queue,
        "open_opportunities": open_opps,
        "upcoming_deadlines": upcoming,
        "review_queue": review_queue,
        "recent_signals": feed[:5],
        "watchlist": [
            {k: t[k] for k in ("id", "name", "future_group_value",
                               "recruitment_likelihood", "last_checked",
                               "next_preparation")}
            for t in watchlist
        ],
        "preparation_actions": prep_actions[:8],
        "meaningful_changes": meaningful_changes,
        "meta": meta,
    }


def people_list(cfg: Config) -> list[dict]:
    """Researchers with their organisation name and contact status."""
    conn = connect(cfg)
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT p.*, g.name AS org_name FROM people p "
            "LEFT JOIN organisations g ON g.id = p.org_id "
            "ORDER BY p.priority IS NULL, p.priority, p.name"
        )]
    finally:
        conn.close()
    return rows


# Rejection reasons that mark a vacancy as timing/stage-limited rather than
# research-mismatched: such rejects with high methodological fit remain
# FUTURE TARGETS for monitoring.
_TIMING_REASONS = {"degree_timing_mismatch", "career_stage_mismatch", "deadline_passed"}


def analytics_scopes(row: dict) -> list[str]:
    """Deterministic analytics-scope membership for one opportunity row.

    Poor-fit vacancies are excluded from every personal scope but remain in
    the full audit database (they are never deleted)."""
    scopes: list[str] = []
    fit_type = row.get("fit_type")
    rec = row.get("recommendation")
    reasons = row.get("rejection_reasons") or []
    if isinstance(reasons, str):
        reasons = json.loads(reasons)

    if fit_type in ("exact-fit", "adjacent-methodological-fit"):
        scopes.append("target_market")
    if rec in ("apply", "consider") or (
        rec == "monitor" and row.get("eligibility_gate") != "fail"
    ):
        scopes.append("actionable")
    if (
        rec == "reject"
        and reasons
        and set(reasons) <= _TIMING_REASONS
        and (row.get("methodological_fit") or 0) >= 60
        and fit_type != "poor-fit"
    ):
        scopes.append("future_target")
    return scopes


def skills_analytics(cfg: Config) -> dict:
    """Per-scope skill statistics with required and preferred counted
    separately. The main personal Skills Radar reads the 'target_market'
    scope — never the full corpus — so poor-fit engineering/science vacancies
    cannot distort it while still being preserved for audit."""
    conn = connect(cfg)
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, org_id, fit_type, recommendation, eligibility_gate, "
            "methodological_fit, required_skills, preferred_skills, "
            "rejection_reasons FROM opportunities WHERE hidden = 0"
        )]
    finally:
        conn.close()

    def empty() -> dict:
        return {"opportunities": 0, "required": {}, "preferred": {}}

    out: dict = {
        "target_market": empty(),
        "actionable": empty(),
        "future_target": empty(),
        "institution_specific": {},
        "full_audit_count": len(rows),
    }

    for row in rows:
        req = json.loads(row["required_skills"] or "[]")
        pref = json.loads(row["preferred_skills"] or "[]")
        scopes = analytics_scopes(row)
        buckets = [out[s] for s in scopes]
        # Institution scope is separate and always populated (per org).
        inst = out["institution_specific"].setdefault(row["org_id"], empty())
        buckets.append(inst)
        for b in buckets:
            b["opportunities"] += 1
            for s in req:
                b["required"][s] = b["required"].get(s, 0) + 1
            for s in pref:
                b["preferred"][s] = b["preferred"].get(s, 0) + 1
    return out


def suggest_skill_status(level: Optional[str], required_count: int,
                         preferred_count: int) -> str:
    """Deterministic suggestion combining market demand and the user's level."""
    if required_count == 0 and preferred_count == 0:
        return "not_relevant"
    if level == "advanced":
        return "strength" if required_count >= 2 else "maintain"
    if level == "intermediate":
        return "maintain" if required_count >= 2 else "optional"
    # beginner / none / unrecorded
    if required_count >= 3:
        return "learn_next"
    return "optional"


def skills_radar(cfg: Config) -> dict:
    """Skills Radar payload: per scope, one row per canonical skill with
    demand counts, supporting opportunities, the user's level/evidence and a
    deterministic suggested status. The primary radar scope is target_market —
    poor-fit vacancies never contribute to it (they remain in the audit)."""
    labels: dict[str, str] = {}
    for group in cfg.taxonomy.values():
        if isinstance(group, list):
            for entry in group:
                if isinstance(entry, dict) and "id" in entry:
                    labels[entry["id"]] = entry.get("label", entry["id"])

    profile: dict[str, dict] = {}
    for s in (cfg.profile.get("skills") or []):
        if isinstance(s, dict) and s.get("id"):
            profile[s["id"]] = s

    conn = connect(cfg)
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, title, org_id, fit_type, recommendation, "
            "eligibility_gate, methodological_fit, required_skills, "
            "preferred_skills, rejection_reasons FROM opportunities "
            "WHERE hidden = 0"
        )]
        org_names = {
            r["id"]: r["name"] for r in conn.execute(
                "SELECT id, name FROM organisations"
            )
        }
    finally:
        conn.close()

    scopes: dict[str, dict] = {
        "target_market": {}, "actionable": {}, "future_target": {},
    }
    institution: dict[str, dict] = {}

    def bump(bucket: dict, skill: str, kind: str, row: dict) -> None:
        entry = bucket.setdefault(skill, {
            "skill": skill,
            "label": labels.get(skill, skill),
            "required_count": 0,
            "preferred_count": 0,
            "supporting": [],
        })
        entry[f"{kind}_count"] += 1
        if not any(s["id"] == row["id"] for s in entry["supporting"]):
            entry["supporting"].append({"id": row["id"], "title": row["title"]})

    scope_totals = {k: 0 for k in scopes}
    inst_totals: dict[str, int] = {}
    for row in rows:
        req = json.loads(row["required_skills"] or "[]")
        pref = json.loads(row["preferred_skills"] or "[]")
        members = [s for s in analytics_scopes(row) if s in scopes]
        for m in members:
            scope_totals[m] += 1
        inst_bucket = institution.setdefault(row["org_id"], {})
        inst_totals[row["org_id"]] = inst_totals.get(row["org_id"], 0) + 1
        for skill in req:
            for m in members:
                bump(scopes[m], skill, "required", row)
            bump(inst_bucket, skill, "required", row)
        for skill in pref:
            for m in members:
                bump(scopes[m], skill, "preferred", row)
            bump(inst_bucket, skill, "preferred", row)

    def finalize(bucket: dict, total: int) -> dict:
        skills = []
        for entry in bucket.values():
            p = profile.get(entry["skill"], {})
            entry["user_level"] = p.get("level")
            entry["user_evidence"] = p.get("evidence")
            entry["suggested_status"] = suggest_skill_status(
                p.get("level"), entry["required_count"], entry["preferred_count"]
            )
            skills.append(entry)
        skills.sort(key=lambda e: (-e["required_count"], -e["preferred_count"], e["skill"]))
        return {"total_opportunities": total, "skills": skills}

    return {
        "scopes": {k: finalize(v, scope_totals[k]) for k, v in scopes.items()},
        "institutions": {
            org: {
                "name": org_names.get(org, org),
                **finalize(bucket, inst_totals.get(org, 0)),
            }
            for org, bucket in institution.items()
        },
    }


def browse_opportunities(cfg: Config, filters: dict) -> list[dict]:
    """Full-audit opportunity browser. Includes rejected and poor-fit records
    by design — nothing is hidden from this view (manual.hidden only)."""
    where = ["1=1"]
    params: list = []
    for column in ("org_id", "lab_org_id", "fit_type", "recommendation",
                   "eligibility_gate", "future_group_value", "position_type",
                   "status", "timing_assessment"):
        value = filters.get(column)
        if value:
            where.append(f"o.{column} = ?")
            params.append(value)
    if filters.get("q"):
        where.append("o.title LIKE ?")
        params.append(f"%{filters['q']}%")

    conn = connect(cfg)
    try:
        rows = [dict(r) for r in conn.execute(
            f"SELECT o.*, g.name AS org_name, l.name AS lab_name "
            f"FROM opportunities o "
            f"LEFT JOIN organisations g ON g.id = o.org_id "
            f"LEFT JOIN organisations l ON l.id = o.lab_org_id "
            f"WHERE {' AND '.join(where)} "
            f"ORDER BY o.deadline IS NULL, o.deadline",
            params,
        )]
    finally:
        conn.close()

    today_iso = date.today().isoformat()
    out = []
    for r in rows:
        r["rejection_reasons"] = json.loads(r["rejection_reasons"] or "[]")
        r["required_skills"] = json.loads(r["required_skills"] or "[]")
        r["preferred_skills"] = json.loads(r["preferred_skills"] or "[]")
        r["eligibility_reasons"] = json.loads(r["eligibility_reasons"] or "[]")
        r["deadline_status"] = (
            "none" if not r["deadline"]
            else ("upcoming" if r["deadline"] >= today_iso else "past")
        )
        if filters.get("rejection_reason") and \
                filters["rejection_reason"] not in r["rejection_reasons"]:
            continue
        if filters.get("skill") and filters["skill"] not in r["required_skills"] \
                and filters["skill"] not in r["preferred_skills"]:
            continue
        if filters.get("deadline_status") and \
                r["deadline_status"] != filters["deadline_status"]:
            continue
        out.append(r)

    # 'relevant' scope (the default Opportunities page, distinct from Archive):
    # exact/adjacent fit, or an apply/consider proposal, or a user-set status.
    if filters.get("scope") == "relevant":
        out = [
            r for r in out
            if r["fit_type"] in ("exact-fit", "adjacent-methodological-fit")
            or r["recommendation"] in ("apply", "consider")
            or r["user_status"]
        ]
    return out


_VALUE_ORDER = {"high": 3, "medium": 2, "low": 1, None: 0}


def targets_data(cfg: Config) -> list[dict]:
    """Target Map: monitored organisations with linked people, opportunities,
    signals, actions and recurring required skills."""
    conn = connect(cfg)
    try:
        orgs = [dict(r) for r in conn.execute("SELECT * FROM organisations")]
        people = [dict(r) for r in conn.execute("SELECT * FROM people")]
        opps = [dict(r) for r in conn.execute(
            "SELECT id, title, org_id, lab_org_id, deadline, status, fit_type, "
            "recommendation, future_group_value, required_skills, "
            "eligibility_gate FROM opportunities WHERE hidden = 0"
        )]
        signals = [dict(r) for r in conn.execute(
            "SELECT * FROM signals WHERE dismissed = 0"
        )]
        actions = [dict(r) for r in conn.execute(
            "SELECT * FROM actions WHERE status IN ('todo','doing')"
        )]
    finally:
        conn.close()

    children: dict[str, list[str]] = {}
    for o in orgs:
        if o["parent_org_id"]:
            children.setdefault(o["parent_org_id"], []).append(o["id"])

    targets = []
    for org in orgs:
        if not org["target"]:
            continue
        family = {org["id"], *children.get(org["id"], [])}
        linked_opps = [
            o for o in opps
            if o["org_id"] in family or (o["lab_org_id"] or "") in family
        ]
        linked_ids = {o["id"] for o in linked_opps}
        linked_people = [p for p in people if (p["org_id"] or "") in family]
        person_ids = {p["id"] for p in linked_people}
        linked_signals = [s for s in signals if (s["org_id"] or "") in family]
        linked_actions = [
            a for a in actions
            if (a["opportunity_id"] or "") in linked_ids
            or (a["person_id"] or "") in person_ids
        ]
        skill_counts: dict[str, int] = {}
        best_value = None
        for o in linked_opps:
            for s in json.loads(o["required_skills"] or "[]"):
                skill_counts[s] = skill_counts.get(s, 0) + 1
            if _VALUE_ORDER[o["future_group_value"]] > _VALUE_ORDER[best_value]:
                best_value = o["future_group_value"]
        targets.append({
            "id": org["id"],
            "name": org["name"],
            "org_type": org["org_type"],
            "priority": org["priority"],
            "research_direction": org["notes"] or "",
            "future_group_value": best_value,
            "people": linked_people,
            "opportunities": sorted(
                linked_opps, key=lambda o: (o["deadline"] is None, o["deadline"] or "")
            ),
            "signals": linked_signals,
            "actions": linked_actions,
            "recurring_skills": sorted(
                skill_counts.items(), key=lambda kv: -kv[1]
            )[:8],
        })
    targets.sort(key=lambda t: (-_VALUE_ORDER[t["future_group_value"]], t["name"]))
    return targets


def signals_feed(cfg: Config) -> list[dict]:
    """Verified signals with linked organisation, people and opportunities."""
    conn = connect(cfg)
    try:
        sigs = [dict(r) for r in conn.execute(
            "SELECT s.*, g.name AS org_name FROM signals s "
            "LEFT JOIN organisations g ON g.id = s.org_id "
            "WHERE s.dismissed = 0 "
            "ORDER BY COALESCE(s.published_at, s.retrieved_at) DESC"
        )]
        people = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM people")}
        opps = {r["id"]: dict(r) for r in conn.execute(
            "SELECT id, title, deadline, recommendation FROM opportunities"
        )}
    finally:
        conn.close()

    for s in sigs:
        s["person_ids"] = json.loads(s["person_ids"] or "[]")
        s["risks"] = json.loads(s["risks"] or "[]")
        s["related_opportunity_ids"] = json.loads(s["related_opportunity_ids"] or "[]")
        s["people"] = [people[p] for p in s["person_ids"] if p in people]
        s["opportunities"] = [
            opps[o] for o in s["related_opportunity_ids"] if o in opps
        ]
    return sigs


# Skill groups considered "methods" for preparation suggestions.
def _taxonomy_groups(cfg: Config) -> dict[str, str]:
    groups: dict[str, str] = {}
    for group_name, entries in cfg.taxonomy.items():
        if isinstance(entries, list):
            for e in entries:
                if isinstance(e, dict) and "id" in e:
                    groups[e["id"]] = group_name
    return groups


def preparation_items(cfg: Config, target: dict) -> list[dict]:
    """Deterministic prepare-before-vacancy suggestions for a target group.
    Returns STRUCTURED items (no baked-in English) so the frontend can localise
    via t() templates. Purely derived; never creates records."""
    profile = {s["id"]: s for s in (cfg.profile.get("skills") or [])
               if isinstance(s, dict) and s.get("id")}
    items: list[dict] = []

    for skill, count in target.get("recurring_skills", []):
        level = (profile.get(skill) or {}).get("level")
        if level == "advanced":
            items.append({"kind": "portfolio", "skill": skill, "count": count})
        elif level in (None, "none"):
            items.append({"kind": "learn", "skill": skill, "count": count})
        elif level == "beginner":
            items.append({"kind": "strengthen", "skill": skill, "count": count})
    for p in target.get("people", [])[:3]:
        items.append({"kind": "monitor_person", "person": p["name"]})
    for s in target.get("signals", [])[:2]:
        if s.get("url"):
            items.append({"kind": "monitor_signal", "source_title": s["title"]})
    return items[:8]


def watchlist_data(cfg: Config) -> list[dict]:
    """Watchlist = target map + latest signals + derived last_checked +
    deterministic preparation items + a next recommended preparation action."""
    targets = targets_data(cfg)
    conn = connect(cfg)
    try:
        sig_rows = [dict(r) for r in conn.execute(
            "SELECT * FROM signals WHERE dismissed = 0"
        )]
        checked = {
            r["org_id"]: r["last"] for r in conn.execute(
                "SELECT org_id, MAX(retrieved_at) AS last FROM opportunities "
                "GROUP BY org_id"
            )
        }
        lab_checked = {
            r["lab_org_id"]: r["last"] for r in conn.execute(
                "SELECT lab_org_id, MAX(retrieved_at) AS last FROM opportunities "
                "WHERE lab_org_id IS NOT NULL GROUP BY lab_org_id"
            )
        }
    finally:
        conn.close()

    for t in targets:
        t["latest_signals"] = [
            {k: s[k] for k in ("id", "title", "signal_type",
                               "recruitment_likelihood", "published_at")}
            for s in sig_rows if (s["org_id"] or "") == t["id"]
        ]
        likelihoods = [s["recruitment_likelihood"] for s in t["latest_signals"]
                       if s["recruitment_likelihood"]]
        order = {"high": 3, "moderate": 2, "low": 1}
        t["recruitment_likelihood"] = max(
            likelihoods, key=lambda x: order[x], default=None
        )
        candidates = [c for c in (
            checked.get(t["id"]), lab_checked.get(t["id"]),
            *(s["retrieved_at"] for s in sig_rows if (s["org_id"] or "") == t["id"]),
        ) if c]
        t["last_checked"] = max(candidates) if candidates else None
        if _VALUE_ORDER[t["future_group_value"]] >= 2:  # high or medium
            t["preparation_items"] = preparation_items(cfg, t)
        else:
            t["preparation_items"] = []
        # Structured next action (frontend localises); None if nothing to do.
        t["next_preparation"] = (
            t["preparation_items"][0] if t["preparation_items"] else None
        )
    return targets


APPLICATION_STAGES = [
    "identified", "preparing", "submitted", "monitoring",
    "awaiting_response", "interview", "offered", "rejected", "withdrawn",
]


def applications_data(cfg: Config) -> dict:
    """Application Pipeline grouped by stage, enriched from the linked
    vacancy (deadline/title always inherited, never duplicated)."""
    conn = connect(cfg)
    try:
        apps = [dict(r) for r in conn.execute("SELECT * FROM applications")]
        opp_map = {
            r["id"]: dict(r) for r in conn.execute(
                "SELECT id, title, deadline, status, canonical_url "
                "FROM opportunities"
            )
        }
    finally:
        conn.close()

    stages: dict[str, list] = {s: [] for s in APPLICATION_STAGES}
    for a in apps:
        a["blockers"] = json.loads(a["blockers"] or "[]")
        a["materials"] = json.loads(a["materials"] or "[]")
        a["documents_used"] = json.loads(a["documents_used"] or "[]")
        a["events"] = json.loads(a["events"] or "[]")
        opp = opp_map.get(a["opportunity_id"])
        a["opportunity_title"] = opp["title"] if opp else a["opportunity_id"]
        a["official_deadline"] = opp["deadline"] if opp else None
        a["opportunity_status"] = opp["status"] if opp else None
        a["official_url"] = opp["canonical_url"] if opp else None
        stages.setdefault(a["stage"], []).append(a)
    for bucket in stages.values():
        bucket.sort(key=lambda a: (a["official_deadline"] is None,
                                   a["official_deadline"] or ""))
    return {"stages": stages, "total": len(apps)}


def opportunity_detail(cfg: Config, store: Store, opp_id: str) -> Optional[dict]:
    """Full detail for the Opportunity workspace: official/ai/derived/manual
    plus organisation names and any linked application. Read from canonical so
    the AI rationales and full text are available. Returns None if missing."""
    if not store.exists("opportunity", opp_id):
        return None
    opp = store.load("opportunity", opp_id)
    o, d, m = opp.official, opp.derived, opp.manual

    def org_name(oid):
        return store.load("organisation", oid).official.name if oid and store.exists(
            "organisation", oid) else oid

    linked = None
    for app in store.load_all("application"):
        if app.system.opportunity_id == opp_id:
            linked = {"id": app.id, "stage": app.manual.stage}
            break

    from .rules import effective_recommendation
    return {
        "id": opp.id,
        "updated_at": opp.updated_at.isoformat() if opp.updated_at else None,
        "official": {
            "title": o.title, "org_id": o.org_id, "org_name": org_name(o.org_id),
            "lab_org_id": o.lab_org_id, "lab_name": org_name(o.lab_org_id),
            "canonical_url": o.canonical_url, "apply_url": o.apply_url,
            "deadline": o.deadline.isoformat() if o.deadline else None,
            "deadline_note": o.deadline_note, "location": o.location,
            "position_type": o.position_type, "salary_text": o.salary_text,
            "funding": o.funding, "status": o.status,
            "description_text": o.description_text,
        },
        "ai": None if opp.ai is None else {
            "summary": opp.ai.summary, "fit_type": opp.ai.fit_type,
            "thematic_fit": opp.ai.thematic_fit.model_dump(),
            "methodological_fit": opp.ai.methodological_fit.model_dump(),
            "growth_value": opp.ai.growth_value.model_dump(),
            "strategic_value": opp.ai.strategic_value.model_dump(),
            "required_skills": opp.ai.required_skills,
            "preferred_skills": opp.ai.preferred_skills,
            "matched_skills": opp.ai.matched_skills,
            "missing_skills": opp.ai.missing_skills,
            "transferable_strengths": opp.ai.transferable_strengths,
            "risks": opp.ai.risks, "recommendation": opp.ai.recommendation,
        },
        "derived": {
            "eligibility_gate": d.eligibility_gate,
            "eligibility_reasons": d.eligibility_reasons,
            "fit_overall": d.fit_overall, "timing_assessment": d.timing_assessment,
            "effective_recommendation": effective_recommendation(
                d.eligibility_gate, opp.ai.recommendation if opp.ai else None),
        },
        "manual": {"user_status": m.user_status, "notes": m.notes, "tags": m.tags},
        "profile_levels": {
            s["id"]: s.get("level") for s in (cfg.profile.get("skills") or [])
            if isinstance(s, dict) and s.get("id")
        },
        "application": linked,
    }


def health_data(cfg: Config) -> dict:
    """System / collector health for the dashboard footer."""
    conn = connect(cfg)
    try:
        meta = {
            row["key"]: row["value"]
            for row in conn.execute("SELECT key, value FROM meta")
        }
    finally:
        conn.close()

    health_path = cfg.paths.status / "collector_health.json"
    if health_path.is_file():
        with open(health_path, encoding="utf-8") as f:
            collectors = json.load(f)
    else:
        collectors = {}

    llm_configured = bool(
        cfg.api_key and cfg.api_base_url and (cfg.models.get("api") or {}).get("model")
    )
    return {
        "index_rebuilt_at": meta.get("rebuilt_at"),
        "entity_counts": json.loads(meta["entity_counts"])
        if "entity_counts" in meta else {},
        "collectors": collectors,
        "llm_configured": llm_configured,
    }
