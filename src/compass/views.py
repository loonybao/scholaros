"""Refresh derived views after a write.

Ordinary user writes (manual annotation, Application edit, Action create) touch
a SINGLE entity, so they update only that entity's SQLite row and its one
generated markdown page — never a full recompute + rebuild + export. The
derived layer is a pure function of (official, constraints, today) and does NOT
depend on manual or application data, so manual/application/action writes never
recompute derived at all.

refresh_all() remains for reconciliation: migrations, bulk collector runs,
schema changes, recovery, or an explicit `rebuild-index` / `export`.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Optional

from .config import Config
from .export_vault import VaultExporter
from .index import (
    rebuild_index, upsert_action, upsert_application, upsert_opportunity,
    upsert_skill_progress,
)
from .perf import Timings
from .rules import recompute_derived
from .store import Store

RECONCILE_MARKER = "needs_reconcile.json"


def recompute_all_derived(cfg: Config, store: Store, today: date | None = None) -> None:
    today = today or date.today()
    for opp in list(store.load_all("opportunity")):
        new_derived = recompute_derived(opp, cfg.constraints, today)
        if new_derived != opp.derived:
            opp.derived = new_derived
            store.save(opp, actor="rules", note="derived layer recomputed")


def refresh_all(cfg: Config, store: Store, today: date | None = None) -> None:
    """Full reconciliation: recompute derived, rebuild the index, regenerate
    the whole vault. Use after migrations, bulk imports, or recovery — NOT for
    ordinary single-entity user writes (see refresh_* below)."""
    today = today or date.today()
    recompute_all_derived(cfg, store, today)
    rebuild_index(cfg, store)
    VaultExporter(cfg, store).export_all(today)


# ------------------------------------------------------------ incremental #

def refresh_opportunity(cfg: Config, store: Store, opp_id: str,
                        tm: Optional[Timings] = None) -> None:
    tm = tm or Timings()
    opp = store.load("opportunity", opp_id)
    with tm.measure("index"):
        upsert_opportunity(cfg, opp)          # derived unchanged by a manual edit
    with tm.measure("vault"):
        VaultExporter(cfg, store).export_opportunity(opp_id)


def refresh_application(cfg: Config, store: Store, app_id: str,
                        tm: Optional[Timings] = None) -> None:
    tm = tm or Timings()
    app = store.load("application", app_id)
    with tm.measure("index"):
        upsert_application(cfg, app)
    with tm.measure("vault"):
        VaultExporter(cfg, store).export_application(app_id)


def refresh_action(cfg: Config, store: Store, act_id: str,
                   tm: Optional[Timings] = None) -> None:
    tm = tm or Timings()
    act = store.load("action", act_id)
    with tm.measure("index"):
        upsert_action(cfg, act)               # no vault page for actions


def refresh_skill_progress(cfg: Config, store: Store, sp_id: str,
                           tm: Optional[Timings] = None) -> None:
    tm = tm or Timings()
    sp = store.load("skill_progress", sp_id)
    with tm.measure("index"):
        upsert_skill_progress(cfg, sp)        # no vault page for skill progress


def _mark_reconcile(cfg: Config, kind: str, entity_id: str, error: str) -> None:
    path = cfg.paths.status / RECONCILE_MARKER
    data = []
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            data = []
    data.append({"kind": kind, "id": entity_id, "error": error,
                 "at": datetime.now(timezone.utc).isoformat()})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def try_refresh(cfg: Config, store: Store, kind: str, entity_id: str,
                tm: Optional[Timings] = None) -> Optional[str]:
    """Run the incremental refresh for one entity. The caller has ALREADY saved
    canonical; if the derived/index/vault update fails we keep the canonical
    change, record a reconcile marker, and return a human-readable warning
    (never silently claim full success). Returns None on success."""
    dispatch = {
        "application": refresh_application,
        "opportunity": refresh_opportunity,
        "action": refresh_action,
        "skill_progress": refresh_skill_progress,
    }
    try:
        dispatch[kind](cfg, store, entity_id, tm)
        return None
    except Exception as e:  # report, never crash a write that already persisted
        _mark_reconcile(cfg, kind, entity_id, str(e))
        return ("Saved. Derived views need reconciliation "
                "(run `python -m compass rebuild-index` then `export`).")
