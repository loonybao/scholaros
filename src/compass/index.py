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

from .config import Config
from .store import Store

SCHEMA = """
DROP TABLE IF EXISTS opportunities;
DROP TABLE IF EXISTS organisations;
DROP TABLE IF EXISTS people;
DROP TABLE IF EXISTS actions;
DROP TABLE IF EXISTS meta;

CREATE TABLE actions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    priority TEXT NOT NULL,
    due_date TEXT,
    opportunity_id TEXT
);

CREATE TABLE organisations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    org_type TEXT NOT NULL,
    country TEXT,
    target INTEGER NOT NULL DEFAULT 0,
    priority TEXT
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
    status TEXT NOT NULL,
    position_type TEXT NOT NULL,
    location TEXT,
    salary_text TEXT,
    needs_review INTEGER NOT NULL DEFAULT 0,
    hidden INTEGER NOT NULL DEFAULT 0,
    analyzed INTEGER NOT NULL DEFAULT 0,
    analysis_stale INTEGER NOT NULL DEFAULT 0
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
                "INSERT INTO organisations VALUES (?,?,?,?,?,?)",
                (
                    org.id,
                    org.official.name,
                    org.official.org_type,
                    org.official.country,
                    int(org.manual.target),
                    org.manual.priority,
                ),
            )
            rows += 1

        from .analysis_io import analysis_input_hash
        from .rules import effective_recommendation

        for opp in store.load_all("opportunity"):
            o, d = opp.official, opp.derived
            stale = bool(
                opp.ai is not None
                and opp.ai.analysis_input_hash != analysis_input_hash(cfg, opp)
            )
            conn.execute(
                "INSERT INTO opportunities VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    opp.id,
                    o.title,
                    o.org_id,
                    o.lab_org_id,
                    o.canonical_url,
                    o.deadline.isoformat() if o.deadline else None,
                    d.days_to_deadline,
                    d.urgency,
                    d.eligibility_gate,
                    json.dumps(d.eligibility_reasons, ensure_ascii=False),
                    d.fit_overall,
                    opp.ai.fit_type if opp.ai else None,
                    effective_recommendation(
                        d.eligibility_gate,
                        opp.ai.recommendation if opp.ai else None,
                    ),
                    opp.ai.analysis_status if opp.ai else None,
                    o.status,
                    o.position_type,
                    o.location,
                    o.salary_text,
                    int(d.needs_review),
                    int(opp.manual.hidden),
                    int(opp.ai is not None),
                    int(stale),
                ),
            )
            rows += 1

        for act in store.load_all("action"):
            conn.execute(
                "INSERT INTO actions VALUES (?,?,?,?,?,?)",
                (
                    act.id,
                    act.manual.title,
                    act.manual.status,
                    act.system.priority,
                    act.system.due_date.isoformat() if act.system.due_date else None,
                    act.system.related.opportunity_id,
                ),
            )
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
        #   - provisional apply/consider recommendations (incl. their imminent
        #     deadlines; if stale, they stay here flagged for renewed attention),
        #   - explicit manual-verification tasks (open Action records, added
        #     to the payload below).
        # Unanalysed records — and stale monitor/reject dispositions, which
        # need re-analysis rather than attention — go to the Analysis Queue.
        for r in all_opps:
            r["analysis_stale"] = bool(r["analysis_stale"])
        action_required = [
            r for r in open_opps if r["recommendation"] in ("apply", "consider")
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

    return {
        "generated_at": today.isoformat(),
        "action_required": action_required,
        "manual_tasks": open_tasks,
        "analysis_queue": analysis_queue,
        "open_opportunities": open_opps,
        "upcoming_deadlines": upcoming,
        "review_queue": review_queue,
        "meta": meta,
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
