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
from .models import Opportunity, OpportunityAI, utcnow
from .store import Store

PROMPT_VERSION = "fit_analysis_v1"

REQUIRED_PROVENANCE = {
    "analysis_provider": "interactive_claude",
    "analysis_mode": "manual_assisted",
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
        "profile": _profile_summary(cfg),
        "target_identity": cfg.target_identity.get("statement"),
        "taxonomy_ids": sorted(cfg.taxonomy_ids()),
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
    cfg: Config, store: Store, result_path: Path, model: str
) -> dict[str, list[str]]:
    """Validate and write analysis results. Returns {imported, rejected}."""
    with open(result_path, encoding="utf-8") as f:
        data = json.load(f)

    imported: list[str] = []
    rejected: list[str] = []

    for item in data.get("results", []):
        opp_id = item.get("id", "<missing id>")
        analysis = item.get("analysis")
        if not isinstance(analysis, dict):
            rejected.append(f"{opp_id}: no analysis object")
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

        # Enforce provenance for the interactive workflow.
        payload = dict(analysis)
        payload.update(REQUIRED_PROVENANCE)
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
