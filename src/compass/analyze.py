"""Analyze stage (live LLM).

Finds opportunities whose ai layer is missing or stale (analysis_input_hash
changed vs the current record + profile + prompt), sends up to the per-run cap
in ONE whitelisted packet, and writes ai.* via analysis_io with automated
provenance. Only new/changed records cost tokens (the whole point of the hash).
`skip_llm=True` is the fallback: report what WOULD be analysed, call nothing.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from .analysis_io import (
    PROMPT_VERSION, analysis_input_hash, import_results_data, live_provenance,
    prepare_packet,
)
from .config import Config
from .llm import BudgetExceeded, LLMClient, LLMError, NotConfigured
from .store import Store


def pending_opportunity_ids(cfg: Config, store: Store) -> list[str]:
    """Opportunities needing (re)analysis: never analysed, or the analysis input
    changed since. Hidden records are skipped."""
    pending: list[str] = []
    for opp in store.load_all("opportunity"):
        if opp.manual.hidden:
            continue
        if opp.ai is None or opp.ai.analysis_input_hash != analysis_input_hash(cfg, opp):
            pending.append(opp.id)
    return pending


def _prompt_text(cfg: Config) -> str:
    path = cfg.paths.config / "prompts" / f"{PROMPT_VERSION}.md"
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def analyze(cfg: Config, store: Store, limit: Optional[int] = None,
            skip_llm: bool = False, today: Optional[date] = None,
            client: Optional[LLMClient] = None) -> dict:
    today = today or date.today()
    client = client or LLMClient(cfg)
    pending = pending_opportunity_ids(cfg, store)
    cap = client.max_items if limit is None else min(limit, client.max_items)
    batch = pending[:cap]

    report: dict = {
        "pending": len(pending), "selected": len(batch),
        "imported": [], "rejected": [], "skipped": False, "error": None,
    }

    if skip_llm:
        report["skipped"] = True
        report["error"] = "skip_llm"
        return report
    if not batch:
        return report
    if not client.configured():
        report["skipped"] = True
        report["error"] = "llm_not_configured"
        return report

    packet = prepare_packet(cfg, store, batch)
    try:
        results = client.analyze_packet(packet, _prompt_text(cfg), today)
    except (NotConfigured, BudgetExceeded) as e:
        report["skipped"] = True
        report["error"] = str(e)
        return report
    except (LLMError, ValueError) as e:
        # bad/unparseable response after retry — leave the ai layer untouched.
        report["error"] = f"invalid_response: {e}"
        return report

    imported = import_results_data(
        cfg, store, results, client.model or "api", live_provenance(client.model or "api"))
    report["imported"] = imported["imported"]
    report["rejected"] = imported["rejected"]
    return report
