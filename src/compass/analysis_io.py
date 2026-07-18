"""Interactive-analysis workflow (S4a).

prepare_packet: export ONLY LLM-whitelisted content for selected opportunities
(official evidence text, profile skill/domain summary, target identity,
non-private constraints, taxonomy) plus a per-opportunity analysis_input_hash.

import_results: validate structured analysis against the OpportunityAI schema
and write it through store.py — ai.* only, official.*/manual.* untouched,
change history recorded, stale or invalid results rejected.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .config import Config
from .models import Opportunity, OpportunityAI, Signal, SignalAI, utcnow
from .store import Store

PROMPT_VERSION = "fit_analysis_v1"
SIGNAL_PROMPT_VERSION = "signal_triage_v1"

REQUIRED_PROVENANCE = {
    "analysis_provider": "interactive_claude",
    "analysis_mode": "manual_assisted",
    "analysis_status": "provisional",
}


def live_provenance(model: str) -> dict[str, str]:
    """Provenance for the automated (live-API) analyze stage. Still provisional —
    a proposal is never auto-finalized regardless of source."""
    return {
        "analysis_provider": model or "api",
        "analysis_mode": "automated",
        "analysis_status": "provisional",
    }


def _profile_summary(cfg: Config) -> dict[str, Any]:
    """Whitelisted profile subset: skills + domains + publications summary.
    Never the full private CV."""
    p = cfg.profile
    return {
        "education": p.get("education"),
        "research_summary": p.get("research_summary"),
        "domains": p.get("domains"),
        "skills": p.get("skills"),
        "publications": p.get("publications"),
    }


def _constraints_summary(cfg: Config) -> dict[str, Any]:
    """Non-private constraints relevant to eligibility observations."""
    c = cfg.constraints
    return {
        "geography": c.get("geography"),
        "languages": c.get("languages"),
        "requires_funding": c.get("requires_funding"),
        "degree_held": c.get("degree_held"),
        "restricted_position_eligibility": c.get("restricted_position_eligibility"),
    }


def analysis_input_hash(cfg: Config, opp: Opportunity) -> str:
    """Hash of everything the analysis actually depends on. Changes when the
    posting text, the profile summary or the prompt version changes."""
    payload = {
        "opportunity_id": opp.id,
        "prompt_version": PROMPT_VERSION,
        "title": opp.official.title,
        "description_text": opp.official.description_text,
        "nationality_restrictions_status": opp.official.nationality_restrictions_status,
        "mobility_requirement_status": opp.official.mobility_requirement_status,
        "profile": _profile_summary(cfg),
        "target_identity": cfg.target_identity.get("statement"),
        "taxonomy_ids": sorted(cfg.taxonomy_ids()),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()


def signal_input_hash(cfg: Config, sig: Signal) -> str:
    payload = {
        "signal_id": sig.id,
        "prompt_version": SIGNAL_PROMPT_VERSION,
        "title": sig.official.title,
        "excerpt": sig.official.excerpt,
        "signal_type": sig.official.signal_type,
        "target_identity": cfg.target_identity.get("statement"),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()


def prepare_packet(cfg: Config, store: Store, ids: list[str]) -> dict[str, Any]:
    whitelist = set((cfg.models.get("context_whitelist") or []))
    required = {
        "opportunity_official_text",
        "taxonomy",
        "profile_skill_summary",
        "profile_domain_summary",
        "target_identity_statement",
    }
    missing = required - whitelist
    if missing:
        raise RuntimeError(
            f"context classes not whitelisted in config/models.yaml: {missing}"
        )

    opportunities = []
    for opp_id in ids:
        opp = store.load("opportunity", opp_id)
        opportunities.append(
            {
                "id": opp.id,
                "official_text": {
                    "title": opp.official.title,
                    "position_type": opp.official.position_type,
                    "location": opp.official.location,
                    "nationality_restrictions_status": opp.official.nationality_restrictions_status,
                    "nationality_restrictions_text": opp.official.nationality_restrictions_text,
                    "description_text": opp.official.description_text,
                },
                "evidence_ids": opp.official.evidence_ids,
                "analysis_input_hash": analysis_input_hash(cfg, opp),
            }
        )

    return {
        "packet_type": "compass-analysis-packet",
        "prompt_version": PROMPT_VERSION,
        "prompt_file": "config/prompts/fit_analysis_v1.md",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "profile": _profile_summary(cfg),
        "target_identity": cfg.target_identity,
        "constraints": _constraints_summary(cfg),
        "taxonomy_ids": sorted(cfg.taxonomy_ids()),
        "opportunities": opportunities,
        "result_contract": {
            "note": (
                "Return {'results': [{'id': ..., 'analysis': {OpportunityAI "
                "fields}}]}. AI layer has NO fact fields: never include salary,"
                " deadline, employment or funding STATUS; funding_assessment is"
                " interpretation only. recommendation never finalizes a "
                "decision. Echo analysis_input_hash per result."
            ),
            "required_provenance": REQUIRED_PROVENANCE,
        },
    }


def import_results(
    cfg: Config, store: Store, result_path: Path, model: str,
    provenance: dict[str, str] = REQUIRED_PROVENANCE,
) -> dict[str, list[str]]:
    """Validate and write analysis results from a file. Returns {imported,
    rejected}."""
    with open(result_path, encoding="utf-8") as f:
        data = json.load(f)
    return import_results_data(cfg, store, data, model, provenance)


def import_results_data(
    cfg: Config, store: Store, data: dict, model: str,
    provenance: dict[str, str] = REQUIRED_PROVENANCE,
) -> dict[str, list[str]]:
    """Validate and write analysis results (ai layer only) from an in-memory
    result object. Shared by the interactive import and the live analyze stage;
    the only difference is `provenance`."""
    imported: list[str] = []
    rejected: list[str] = []

    for item in data.get("results", []):
        opp_id = item.get("id", "<missing id>")
        analysis = item.get("analysis")
        if not isinstance(analysis, dict):
            rejected.append(f"{opp_id}: no analysis object")
            continue

        if item.get("entity") == "signal":
            _import_signal(cfg, store, opp_id, analysis, model,
                           imported, rejected, provenance)
            continue

        if not store.exists("opportunity", opp_id):
            rejected.append(f"{opp_id}: unknown opportunity")
            continue

        opp = store.load("opportunity", opp_id)

        # Guard: the result may not smuggle fact-layer content.
        forbidden = {"official", "manual", "derived", "salary_text", "deadline",
                     "status", "funding"} & set(analysis)
        if forbidden:
            rejected.append(f"{opp_id}: forbidden fields in analysis: {forbidden}")
            continue

        # Staleness: the analysis must be based on the CURRENT record + config.
        current_hash = analysis_input_hash(cfg, opp)
        claimed = analysis.get("analysis_input_hash")
        if claimed != current_hash:
            rejected.append(
                f"{opp_id}: stale analysis_input_hash (record or profile "
                f"changed since the packet was prepared)"
            )
            continue

        # Stamp provenance (interactive vs live-automated).
        payload = dict(analysis)
        payload.update(provenance)
        payload["model"] = model
        payload["prompt_version"] = PROMPT_VERSION
        payload.setdefault("analyzed_at", utcnow().isoformat())

        try:
            ai = OpportunityAI.model_validate(payload)
        except ValidationError as e:
            rejected.append(f"{opp_id}: schema validation failed: {e.errors()[:3]}")
            continue

        opp.ai = ai  # ONLY the ai layer is assigned; official/manual untouched
        store.save(opp, actor="ai", note=f"interactive analysis ({model})")
        imported.append(opp_id)

    return {"imported": imported, "rejected": rejected}


def _import_signal(
    cfg: Config, store: Store, sig_id: str, analysis: dict, model: str,
    imported: list[str], rejected: list[str],
    provenance: dict[str, str] = REQUIRED_PROVENANCE,
) -> None:
    """Signal triage import: SignalAI layer only, same guarantees as
    opportunity imports (staleness, no fact fields, provenance)."""
    if not store.exists("signal", sig_id):
        rejected.append(f"{sig_id}: unknown signal")
        return
    sig = store.load("signal", sig_id)

    forbidden = {"official", "manual", "url", "published_at", "org_id"} & set(analysis)
    if forbidden:
        rejected.append(f"{sig_id}: forbidden fields in analysis: {forbidden}")
        return

    current_hash = signal_input_hash(cfg, sig)
    if analysis.get("analysis_input_hash") != current_hash:
        rejected.append(f"{sig_id}: stale analysis_input_hash")
        return

    payload = dict(analysis)
    payload.update(provenance)
    payload["model"] = model
    payload["prompt_version"] = SIGNAL_PROMPT_VERSION
    payload.setdefault("analyzed_at", utcnow().isoformat())
    try:
        ai = SignalAI.model_validate(payload)
    except ValidationError as e:
        rejected.append(f"{sig_id}: schema validation failed: {e.errors()[:3]}")
        return
    sig.ai = ai
    store.save(sig, actor="ai", note=f"interactive signal triage ({model})")
    imported.append(sig_id)
