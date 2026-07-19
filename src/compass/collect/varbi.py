"""Varbi collector — one collector for the many Nordic universities that use the
Varbi ATS (KTH, Chalmers, Lund, Uppsala, Umeå, Linköping, …). Institutions are
listed in config/sources.yaml under the `varbi` source; adding another Varbi
school is a config entry, not new code.

Listing: <institution>.varbi.com/en/ — a server-rendered table, one row per
vacancy: title (linking to /en/what:job/jobID:<id>/), city, department, and an
ISO application deadline. Detail: that job page's main column holds the full
description. Only the official layer is written; the three-way discovery filter
keeps non-research listings out (audited).
"""

from __future__ import annotations

import re
from datetime import date
from typing import Optional

from bs4 import BeautifulSoup

from ..config import Config
from ..store import Store
from .base import (
    CollectStats, RawPosting, audit_discovery, classify_listing,
    detect_mobility, detect_restrictions, ensure_organisation, fetch,
    save_evidence, save_snapshot, upsert_opportunity,
)

SOURCE_ID = "varbi"
_JOBID = re.compile(r"jobID:(\d+)")


def listing_url(base_url: str) -> str:
    return base_url.rstrip("/") + "/en/"


def parse_listing(html: str) -> list[dict]:
    """One entry per vacancy row: {native_id, url, title, city, department,
    deadline}."""
    soup = BeautifulSoup(html, "html.parser")
    entries: list[dict] = []
    seen: set[str] = set()
    for tr in soup.select("tr"):
        a = tr.select_one("a[href*='what:job/jobID:']")
        if not a:
            continue
        m = _JOBID.search(a.get("href", ""))
        if not m or m.group(1) in seen:
            continue
        seen.add(m.group(1))
        tds = tr.select("td")

        def cell(i: int) -> Optional[str]:
            return " ".join(tds[i].get_text(" ", strip=True).split()) if len(tds) > i else None

        deadline = None
        if len(tds) > 3:
            dm = re.search(r"\d{4}-\d{2}-\d{2}", tds[3].get_text())
            if dm:
                try:
                    deadline = date.fromisoformat(dm.group(0))
                except ValueError:
                    deadline = None
        entries.append({
            "native_id": m.group(1),
            "url": a.get("href", ""),
            "title": " ".join(a.get_text(" ", strip=True).split()),
            "city": cell(1),
            "department": cell(2),
            "deadline": deadline,
        })
    return entries


def parse_detail(html: str) -> dict:
    """Extract the full posting text from the job page's main column."""
    soup = BeautifulSoup(html, "html.parser")
    el = (soup.select_one("div.col-md-8")
          or soup.select_one("main")
          or soup.select_one("article"))
    text = ""
    if el is not None:
        text = re.sub(r"\n{3,}", "\n\n", el.get_text("\n", strip=True))[:20000]
    return {"description_text": text}


def collect(cfg: Config, store: Store) -> CollectStats:
    stats = CollectStats()
    src_cfg = next(
        (s for s in cfg.sources.get("sources", []) if s["id"] == SOURCE_ID), {})
    rate = float(src_cfg.get("rate_limit_seconds", 8))

    for inst in src_cfg.get("institutions", []):
        _collect_institution(cfg, store, inst, rate, stats)
    return stats


def _collect_institution(cfg: Config, store: Store, inst: dict, rate: float,
                         stats: CollectStats) -> None:
    org_id = inst["org_id"]
    ensure_organisation(store, org_id, inst["name"], "university", None, SOURCE_ID)
    country = inst.get("country")

    listing_html = fetch(listing_url(inst["base_url"]), rate_limit_seconds=rate)
    save_snapshot(cfg, SOURCE_ID, f"{inst['id']}_listing", listing_html)
    entries = parse_listing(listing_html)
    stats.fetched += len(entries)

    for entry in entries:
        category, _ptype, reason = classify_listing(entry["title"])
        if category != "accepted":
            audit_discovery(cfg, SOURCE_ID, entry["native_id"], entry["title"],
                            entry["url"], category, reason)
            if category == "candidate":
                stats.candidates += 1
            else:
                stats.skipped_irrelevant += 1
            continue
        stats.relevant += 1

        detail_html = fetch(entry["url"], rate_limit_seconds=rate)
        _, snapshot_hash = save_snapshot(
            cfg, SOURCE_ID, f"{inst['id']}_{entry['native_id']}", detail_html)
        detail = parse_detail(detail_html)
        location = ", ".join(x for x in (entry["city"], country) if x)
        evidence_id = save_evidence(cfg, SOURCE_ID, f"{inst['id']}-{entry['native_id']}",
                                    entry["url"], detail["description_text"])
        restriction_status, restriction_text = detect_restrictions(detail["description_text"])
        mobility_status, mobility_text = detect_mobility(detail["description_text"])

        posting = RawPosting(
            source=SOURCE_ID,
            source_native_id=f"{inst['id']}-{entry['native_id']}",
            canonical_url=entry["url"],
            title=entry["title"],
            org_id=org_id,
            deadline=entry["deadline"],
            posted_date=None,
            location=location or None,
            description_text=detail["description_text"],
            nationality_restrictions_status=restriction_status,
            nationality_restrictions_text=restriction_text,
            mobility_requirement_status=mobility_status,
            mobility_requirement_text=mobility_text,
            raw_snapshot_hash=snapshot_hash,
            evidence_id=evidence_id,
        )
        outcome = upsert_opportunity(store, posting)
        setattr(stats, outcome, getattr(stats, outcome) + 1)
