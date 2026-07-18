"""Collectors: fetch official sources and upsert opportunities.

Each source module implements `collect(cfg, store) -> CollectStats`.
Collectors are fail-soft: one broken source never blocks the others, and every
run updates data/status/collector_health.json (surfaced on the dashboard).
"""

from __future__ import annotations

from .base import CollectStats, update_health

SOURCE_MODULES = {
    "aalto": "compass.collect.aalto",
    "tampere": "compass.collect.tampere",
    "tudelft": "compass.collect.tudelft",
    # "euraxess": "compass.collect.euraxess",  # S5b
}


def run_collectors(cfg, store, only_source: str | None = None) -> dict[str, CollectStats]:
    import importlib

    configured = {s["id"]: s for s in cfg.sources.get("sources", [])}
    results: dict[str, CollectStats] = {}

    for source_id, module_path in SOURCE_MODULES.items():
        if only_source and source_id != only_source:
            continue
        if not only_source and not configured.get(source_id, {}).get("enabled"):
            continue
        module = importlib.import_module(module_path)
        try:
            stats = module.collect(cfg, store)
            update_health(cfg, source_id, ok=True, stats=stats)
            results[source_id] = stats
        except Exception as exc:  # fail-soft: record, continue with next source
            update_health(cfg, source_id, ok=False, error=str(exc))
            results[source_id] = CollectStats(error=str(exc))
    return results
