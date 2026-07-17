"""Shared collector infrastructure: HTTP fetch with politeness, raw snapshots,
evidence records, content hashing, relevance prefilter, and opportunity upsert.

Ownership rules (CLAUDE.md): collectors write ONLY the official layer (plus
evidence/raw/status files). They never touch ai/derived/manual layers.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional

import requests

from ..config import Config
from ..models import Opportunity, OpportunityOfficial, utcnow
from ..store import Store

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "ResearchCompass/0.1 (personal academic job tracker; low volume)"
)


@dataclass
class CollectStats:
    fetched: int = 0
    relevant: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped_irrelevant: int = 0
    error: Optional[str] = None


@dataclass
class RawPosting:
    """Official facts extracted by a parser. No interpretation."""

    source: str
    source_native_id: str
    canonical_url: str
    title: str
    org_id: str
    deadline: Optional[date] = None
    deadline_note: Optional[str] = None
    posted_date: Optional[date] = None
    apply_url: Optional[str] = None
    location: Optional[str] = None
    description_text: str = ""
    language_requirements: list[str] = field(default_factory=list)
    nationality_restrictions_status: str = "none_stated"
    nationality_restrictions_text: Optional[str] = None
    raw_snapshot_hash: Optional[str] = None
    evidence_id: Optional[str] = None


# ------------------------------------------------------------------ fetching #

def fetch(url: str, rate_limit_seconds: float = 5.0, timeout: int = 30) -> str:
    """Polite GET. Sleeps rate_limit_seconds BEFORE the request so loops are
    throttled without extra bookkeeping."""
    time.sleep(rate_limit_seconds)
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def save_snapshot(cfg: Config, source: str, name: str, content: str) -> tuple[str, str]:
    """Save raw HTML to data/raw/<source>/. Returns (relative_path, sha256)."""
    digest = sha256_text(content)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
    rel = f"{source}/{stamp}_{safe}_{digest[:8]}.html"
    path = cfg.paths.raw / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    return rel, digest


def save_evidence(
    cfg: Config, source: str, native_id: str, url: str, cleaned_text: str
) -> str:
    """Save cleaned, versioned source evidence (git-tracked). Returns the
    evidence id referenced from official.evidence_ids. Re-saving identical
    content is a no-op; changed content overwrites (git history keeps
    versions)."""
    evidence_id = f"{source}/{re.sub(r'[^a-zA-Z0-9_-]', '_', native_id)}"
    path = cfg.paths.evidence / f"{evidence_id}.md"
    content = (
        f"---\nsource: {source}\nnative_id: {native_id}\nurl: {url}\n"
        f"retrieved_at: {datetime.now(timezone.utc).isoformat()}\n---\n\n"
        f"{cleaned_text}\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        existing = path.read_text(encoding="utf-8")
        # Ignore the retrieved_at line when deciding whether content changed.
        strip = lambda t: re.sub(r"retrieved_at: [^\n]+", "", t)  # noqa: E731
        if strip(existing) == strip(content):
            return evidence_id
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    return evidence_id


# ------------------------------------------------------- relevance prefilter #

# Position-type detection (field-agnostic; domain fit is the LLM's job in S4).
_POSITION_PATTERNS: list[tuple[str, str]] = [
    (r"doctoral\s+researcher|doctoral\s+student|phd\s+(student|position|candidate|researcher)|väitöskirjatutkija", "phd"),
    (r"postdoc|post-doctoral|postdoctoral", "postdoc"),
    (r"project\s+researcher|projektitutkija", "project_researcher"),
    (r"research\s+assistant|tutkimusapulainen", "research_assistant"),
    (r"\bresearcher\b|\btutkija\b", "other"),
]


def classify_position_type(title: str) -> Optional[str]:
    """Return position_type if the title looks like a research position we
    track, else None (skip). Purely mechanical — no domain judgment."""
    t = title.lower()
    for pattern, ptype in _POSITION_PATTERNS:
        if re.search(pattern, t):
            return ptype
    return None


_RESTRICTION_HINTS = re.compile(
    r"export.control|sanction|security\s+clearance|citizenship\s+requirement|"
    r"nationality\s+restriction|defen[cs]e\s+clearance",
    re.IGNORECASE,
)


def detect_restrictions(text: str) -> tuple[str, Optional[str]]:
    """Mechanical detection of restriction MENTIONS. Returns (status, excerpt).
    Only ever yields 'none_stated' or 'ambiguous' — a definitive 'stated'
    classification requires human (or S4 reviewed-AI) confirmation."""
    m = _RESTRICTION_HINTS.search(text)
    if not m:
        return "none_stated", None
    start = max(0, m.start() - 120)
    excerpt = re.sub(r"\s+", " ", text[start : m.end() + 200]).strip()
    return "ambiguous", f"Posting mentions: …{excerpt}…"


# ------------------------------------------------------------------- hashing #

def extracted_content_hash(posting: RawPosting) -> str:
    """Hash of the official fields that matter for change detection."""
    payload = {
        "title": posting.title,
        "deadline": posting.deadline.isoformat() if posting.deadline else None,
        "posted_date": posting.posted_date.isoformat() if posting.posted_date else None,
        "location": posting.location,
        "description_text": posting.description_text,
        "nationality_restrictions_status": posting.nationality_restrictions_status,
    }
    return sha256_text(json.dumps(payload, sort_keys=True, ensure_ascii=False))


# -------------------------------------------------------------------- upsert #

def upsert_opportunity(store: Store, posting: RawPosting) -> str:
    """Create or update an Opportunity from official facts.

    Returns 'created' | 'updated' | 'unchanged'. Identity per CLAUDE.md:
    native_id -> normalized canonical_url -> fingerprint (deadline excluded).
    Only the official layer is written; a deadline change updates the existing
    record (change history is appended by store.save's diff).
    """
    new_hash = extracted_content_hash(posting)
    with store.lock():
        existing = store.find_opportunity(
            posting.source_native_id,
            posting.canonical_url,
            posting.org_id,
            posting.title,
            posting.location,
            posting.posted_date.isoformat() if posting.posted_date else None,
        )
        actor = f"collector:{posting.source}"

        if existing is None:
            official = OpportunityOfficial(
                title=posting.title,
                org_id=posting.org_id,
                source=posting.source,
                source_native_id=posting.source_native_id,
                canonical_url=posting.canonical_url,
                apply_url=posting.apply_url,
                evidence_ids=[posting.evidence_id] if posting.evidence_id else [],
                retrieved_at=utcnow(),
                raw_snapshot_hash=posting.raw_snapshot_hash,
                extracted_content_hash=new_hash,
                deadline=posting.deadline,
                deadline_note=posting.deadline_note,
                posted_date=posting.posted_date,
                position_type=classify_position_type(posting.title) or "other",
                location=posting.location,
                language_requirements=posting.language_requirements,
                nationality_restrictions_status=posting.nationality_restrictions_status,
                nationality_restrictions_text=posting.nationality_restrictions_text,
                status="open",
                description_text=posting.description_text,
            )
            opp = Opportunity(
                id=store.new_id("opportunity", f"{posting.source}-{posting.title}"),
                official=official,
            )
            store.save(opp, actor=actor, note="discovered by collector")
            return "created"

        if existing.official.extracted_content_hash == new_hash and (
            existing.official.source_native_id == posting.source_native_id
        ):
            return "unchanged"

        o = existing.official
        o.title = posting.title
        o.source = posting.source
        o.source_native_id = posting.source_native_id
        o.canonical_url = posting.canonical_url
        o.apply_url = posting.apply_url or o.apply_url
        o.retrieved_at = utcnow()
        o.raw_snapshot_hash = posting.raw_snapshot_hash
        o.extracted_content_hash = new_hash
        o.deadline = posting.deadline
        o.deadline_note = posting.deadline_note or o.deadline_note
        o.posted_date = posting.posted_date or o.posted_date
        o.location = posting.location or o.location
        o.description_text = posting.description_text or o.description_text
        o.status = "open"
        if posting.evidence_id and posting.evidence_id not in o.evidence_ids:
            o.evidence_ids.append(posting.evidence_id)
        # Restrictions: a collector may raise none_stated -> ambiguous but
        # never overwrite a human-confirmed 'stated'.
        if o.nationality_restrictions_status == "none_stated":
            o.nationality_restrictions_status = posting.nationality_restrictions_status
            o.nationality_restrictions_text = posting.nationality_restrictions_text
        saved = store.save(existing, actor=actor, note="official facts refreshed")
        changed = saved.change_history[-1].actor == actor if saved.change_history else False
        return "updated" if changed else "unchanged"


# -------------------------------------------------------------------- health #

def update_health(
    cfg: Config,
    source: str,
    ok: bool,
    stats: CollectStats | None = None,
    error: str | None = None,
) -> None:
    path = cfg.paths.status / "collector_health.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        with open(path, encoding="utf-8") as f:
            health = json.load(f)
    else:
        health = {}
    entry = health.get(source, {})
    now = datetime.now(timezone.utc).isoformat()
    entry["last_run"] = now
    if ok:
        entry["last_success"] = now
        entry["consecutive_errors"] = 0
        entry["last_error"] = None
        if stats:
            entry["last_stats"] = {
                "fetched": stats.fetched,
                "relevant": stats.relevant,
                "created": stats.created,
                "updated": stats.updated,
                "unchanged": stats.unchanged,
                "skipped_irrelevant": stats.skipped_irrelevant,
            }
    else:
        entry["consecutive_errors"] = entry.get("consecutive_errors", 0) + 1
        entry["last_error"] = error
    health[source] = entry
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(health, f, indent=2, ensure_ascii=False)
