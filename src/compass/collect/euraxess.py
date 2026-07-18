"""EURAXESS collector (S13) — the pan-European research-jobs aggregator.

EURAXESS lists ~9,000 vacancies, so this collector is scoped by KEYWORD (the
user's core research terms in config/sources.yaml) rather than crawling
everything — a keyword search returns a small, relevant set instead of flooding
the database. It is disabled by default; enable + tune the keywords after
reviewing the scope.

Listing: server-rendered ECL HTML (euraxess.ec.europa.eu/jobs/search). Each card
(`article.ecl-content-item`) gives title, the /jobs/<id> link (native id), the
employer + its stable profile slug, the posted date, the country label and a
description snippet. This is a monitoring feed: v1 is listing-only (no per-job
detail fetch); the deadline/full text live one click away at the canonical URL.

Every employer becomes a namespaced `org_euraxess_<slug>` (org_type "other").
Cross-source merge into an existing university org (e.g. TU Delft) is a
deliberate future pass — these orgs are never auto-marked as targets, so they do
not clutter the Target Map. Only the official layer is written; the three-way
discovery filter keeps non-research listings out of canonical (audited).
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from ..config import Config
from ..store import Store
from .base import (
    CollectStats, RawPosting, audit_discovery, classify_listing,
    detect_mobility, detect_restrictions, ensure_organisation, fetch,
    save_evidence, save_snapshot, upsert_opportunity,
)

SOURCE_ID = "euraxess"
BASE = "https://euraxess.ec.europa.eu"
SEARCH_URL = BASE + "/jobs/search"
_OFFER_LABELS = {"JOB", "FUNDING", "HOSTING"}


def search_url(keyword: str, page: int = 0) -> str:
    url = f"{SEARCH_URL}?keywords={quote_plus(keyword)}"
    return url if page <= 0 else f"{url}&page={page}"


def canonical_url_for(native_id: str) -> str:
    return f"{BASE}/jobs/{native_id}"


def _parse_posted(text: str) -> Optional[date]:
    text = text.strip()
    for fmt in ("%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _org_id(slug: str, name: str) -> str:
    base = slug or re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    safe = re.sub(r"[^a-z0-9-]+", "-", base.lower()).strip("-")[:60] or "unknown"
    return f"org_euraxess_{safe}".rstrip("-")


def parse_listing(html: str) -> list[dict]:
    """Extract one entry per result card. Robust to missing optional fields."""
    soup = BeautifulSoup(html, "html.parser")
    entries: list[dict] = []
    seen: set[str] = set()
    for art in soup.select("article.ecl-content-item"):
        title_a = art.select_one("h3.ecl-content-block__title a")
        if not title_a:
            continue
        m = re.search(r"/jobs/(\d+)", title_a.get("href", ""))
        if not m:
            continue
        native_id = m.group(1)
        if native_id in seen:
            continue
        seen.add(native_id)

        title = " ".join(title_a.get_text(" ", strip=True).split())
        org_a = art.select_one(
            ".ecl-content-block__primary-meta-container a[href*='/organisations/']")
        org_name = org_a.get_text(" ", strip=True) if org_a else "Unknown organisation"
        slug_m = re.search(r"/profile/([^/?#]+)", org_a.get("href", "")) if org_a else None
        org_slug = slug_m.group(1) if slug_m else ""

        posted = None
        for li in art.select(".ecl-content-block__primary-meta-item"):
            pm = re.search(r"Posted on:\s*(.+)", li.get_text(" ", strip=True))
            if pm:
                posted = _parse_posted(pm.group(1))

        desc_el = art.select_one(".ecl-content-block__description")
        description = " ".join(desc_el.get_text(" ", strip=True).split()) if desc_el else ""

        country = None
        parent = art.parent
        if parent is not None:
            for lab in parent.select(".ecl-content-block__label-item .ecl-label"):
                txt = lab.get_text(strip=True)
                if txt and txt.upper() not in _OFFER_LABELS:
                    country = txt
                    break

        entries.append({
            "native_id": native_id, "title": title,
            "org_name": org_name, "org_slug": org_slug,
            "posted_date": posted, "country": country, "description": description,
        })
    return entries


def collect(cfg: Config, store: Store) -> CollectStats:
    stats = CollectStats()
    src_cfg = next(
        (s for s in cfg.sources.get("sources", []) if s["id"] == SOURCE_ID), {})
    keywords: list[str] = src_cfg.get("keywords") or []
    max_pages = int(src_cfg.get("max_pages", 1))
    rate = float(src_cfg.get("rate_limit_seconds", 5))

    seen_ids: set[str] = set()
    for keyword in keywords:
        for page in range(max_pages):
            html = fetch(search_url(keyword, page), rate_limit_seconds=rate)
            save_snapshot(cfg, SOURCE_ID, f"search_{keyword}_{page}", html)
            entries = [e for e in parse_listing(html) if e["native_id"] not in seen_ids]
            if not entries:
                break                       # no new results on this page -> stop paging
            for entry in entries:
                seen_ids.add(entry["native_id"])
                stats.fetched += 1
                _ingest(cfg, store, entry, stats)
    return stats


def _ingest(cfg: Config, store: Store, entry: dict, stats: CollectStats) -> None:
    url = canonical_url_for(entry["native_id"])
    category, _ptype, reason = classify_listing(entry["title"])
    if category != "accepted":
        audit_discovery(cfg, SOURCE_ID, entry["native_id"], entry["title"],
                        url, category, reason)
        if category == "candidate":
            stats.candidates += 1
        else:
            stats.skipped_irrelevant += 1
        return
    stats.relevant += 1

    org_id = _org_id(entry["org_slug"], entry["org_name"])
    ensure_organisation(store, org_id, entry["org_name"], "other", None, SOURCE_ID)

    _, snapshot_hash = save_snapshot(
        cfg, SOURCE_ID, f"job_{entry['native_id']}", entry["description"] or entry["title"])
    evidence_id = save_evidence(cfg, SOURCE_ID, entry["native_id"], url,
                                entry["description"] or entry["title"])
    restriction_status, restriction_text = detect_restrictions(entry["description"])
    mobility_status, mobility_text = detect_mobility(entry["description"])

    posting = RawPosting(
        source=SOURCE_ID,
        source_native_id=entry["native_id"],
        canonical_url=url,
        title=entry["title"],
        org_id=org_id,
        posted_date=entry["posted_date"],
        location=entry["country"],
        description_text=entry["description"],
        nationality_restrictions_status=restriction_status,
        nationality_restrictions_text=restriction_text,
        mobility_requirement_status=mobility_status,
        mobility_requirement_text=mobility_text,
        raw_snapshot_hash=snapshot_hash,
        evidence_id=evidence_id,
    )
    outcome = upsert_opportunity(store, posting)
    setattr(stats, outcome, getattr(stats, outcome) + 1)
