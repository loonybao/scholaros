"""Refresh derived views after a write: recompute the derived layer, rebuild
the SQLite index, and regenerate the Obsidian vault. Shared by the CLI and the
web write layer so a manual edit is immediately reflected everywhere."""

from __future__ import annotations

from datetime import date

from .config import Config
from .export_vault import VaultExporter
from .index import rebuild_index
from .rules import recompute_derived
from .store import Store


def recompute_all_derived(cfg: Config, store: Store, today: date | None = None) -> None:
    today = today or date.today()
    for opp in list(store.load_all("opportunity")):
        new_derived = recompute_derived(opp, cfg.constraints, today)
        if new_derived != opp.derived:
            opp.derived = new_derived
            store.save(opp, actor="rules", note="derived layer recomputed")


def refresh_all(cfg: Config, store: Store, today: date | None = None) -> None:
    """Recompute derived, rebuild the index, regenerate vault/generated."""
    today = today or date.today()
    recompute_all_derived(cfg, store, today)
    rebuild_index(cfg, store)
    VaultExporter(cfg, store).export_all(today)
