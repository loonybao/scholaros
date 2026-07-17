"""Tampere University collector.

Listing: the official tuni.fi English open-positions page (server-rendered
Drupal/Next HTML) — anchors to the LAURA ATS (tuni.rekrytointi.com) with a
`jid` query param, each followed by an "Application period ends: …" line.
Detail: the ATS page's `div.job_description#jid<NN>` plus
`div.job_start_end_times` and the apply link.

Caveat (sources.yaml): the English page lists only positions published in
English; Finnish-only roles appear on the Finnish page and are out of scope.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Optional
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from ..config import Config
from ..store import Store
from .base import (
    CollectStats,
    RawPosting,
    classify_position_type,
    detect_restrictions,
    fetch,
    save_evidence,
    save_snapshot,
    upsert_opportunity,
)

SOURCE_ID = "tampere"
ORG_ID = "org_tampere_university"
LISTING_URL = "https://www.tuni.fi/en/tau/work-with-us/open-positions"
LOCATION = "Tampere, Finland"

_DEADLINE_RE = re.compile(
    r"Application period ends:\s*(\d{4}-\d{2}-\d{2})(?:\s+(\d{2}:\d{2}))?"
)

# Signals that a " / "-separated segment is the Finnish half of the title.
_FINNISH_HINT = re.compile(
    r"[äöå]|tutkija|tehtävä|insinööri|apulainen|professori|työntekijä",
    re.IGNORECASE,
)


def english_title(title: str) -> str:
    """tuni.fi titles are 'English title / Finnish title'. Drop the Finnish
    half only when it actually looks Finnish — some English titles legitimately
    contain ' / ' (e.g. 'Research Assistant / M.Sc. thesis worker (...)')."""
    parts = title.split(" / ")
    # Walk back from the end: the Finnish half is the maximal tail of segments
    # that each look Finnish. Everything before it is the English title.
    boundary = len(parts)
    while boundary > 1 and _FINNISH_HINT.search(parts[boundary - 1]):
        boundary -= 1
    return " / ".join(parts[:boundary]).strip()


def parse_listing(html: str) -> list[dict]:
    """Extract {native_id, url, title, deadline, deadline_note} entries."""
    soup = BeautifulSoup(html, "html.parser")
    entries: list[dict] = []
    seen: set[str] = set()
    for a in soup.select("a[href*='rekrytointi.com/paikat/']"):
        href = a.get("href", "")
        qs = parse_qs(urlparse(href).query)
        jid = (qs.get("jid") or [None])[0]
        if not jid or jid in seen:
            continue
        title = a.get_text(" ", strip=True)
        if not title:
            continue
        title_en = english_title(title)
        deadline, note = None, None
        container = a
        for _ in range(3):  # walk up to find the sibling deadline line
            container = container.parent
            if container is None:
                break
            m = _DEADLINE_RE.search(container.get_text(" ", strip=True))
            if m:
                deadline = date.fromisoformat(m.group(1))
                note = f"{m.group(2)} local time" if m.group(2) else None
                break
        seen.add(jid)
        entries.append(
            {
                "native_id": jid,
                "url": href,
                "title": title_en,
                "deadline": deadline,
                "deadline_note": note,
            }
        )
    return entries


def parse_detail(html: str, native_id: str) -> dict:
    """Extract description text, posted date, deadline and apply URL."""
    soup = BeautifulSoup(html, "html.parser")
    out: dict = {
        "description_text": "",
        "posted_date": None,
        "deadline": None,
        "deadline_note": None,
        "apply_url": None,
    }

    desc = soup.find("div", class_="job_description", id=f"jid{native_id}") or soup.find(
        "div", class_="job_description"
    )
    if desc is not None:
        text = desc.get_text("\n", strip=True)
        text = re.sub(r"\n{3,}", "\n\n", text)
        out["description_text"] = text[:20000]

    times = soup.find("div", class_="job_start_end_times")
    if times is not None:
        t = times.get_text(" ", strip=True)
        m = re.search(r"starts:\s*(\d{4}-\d{2}-\d{2})", t)
        if m:
            out["posted_date"] = date.fromisoformat(m.group(1))
        m = re.search(r"ends:\s*(\d{4}-\d{2}-\d{2})(?:\s+(\d{2}:\d{2}))?", t)
        if m:
            out["deadline"] = date.fromisoformat(m.group(1))
            out["deadline_note"] = (
                f"{m.group(2)} local time" if m.group(2) else None
            )

    apply_div = soup.find("div", class_="apply_to_job")
    if apply_div is not None:
        a = apply_div.find("a")
        if a and a.get("href"):
            # Strip the volatile session token from the stored apply URL.
            out["apply_url"] = re.sub(r"&?rspvt=[^&#]+", "", a["href"])
    return out


def canonical_url_for(jid: str) -> str:
    return f"https://tuni.rekrytointi.com/paikat/?o=A_RJ&jgid=3&jid={jid}"


def collect(cfg: Config, store: Store) -> CollectStats:
    stats = CollectStats()
    src_cfg = next(
        (s for s in cfg.sources.get("sources", []) if s["id"] == SOURCE_ID), {}
    )
    rate = float(src_cfg.get("rate_limit_seconds", 5))

    listing_html = fetch(LISTING_URL, rate_limit_seconds=0)
    save_snapshot(cfg, SOURCE_ID, "listing", listing_html)
    entries = parse_listing(listing_html)
    stats.fetched = len(entries)

    for entry in entries:
        if classify_position_type(entry["title"]) is None:
            stats.skipped_irrelevant += 1
            continue
        stats.relevant += 1

        detail_url = canonical_url_for(entry["native_id"]) + "&lang=en"
        detail_html = fetch(detail_url, rate_limit_seconds=rate)
        _, snapshot_hash = save_snapshot(
            cfg, SOURCE_ID, f"jid{entry['native_id']}", detail_html
        )
        detail = parse_detail(detail_html, entry["native_id"])

        restriction_status, restriction_text = detect_restrictions(
            detail["description_text"]
        )
        evidence_id = save_evidence(
            cfg,
            SOURCE_ID,
            entry["native_id"],
            canonical_url_for(entry["native_id"]),
            detail["description_text"],
        )

        posting = RawPosting(
            source=SOURCE_ID,
            source_native_id=entry["native_id"],
            canonical_url=canonical_url_for(entry["native_id"]),
            title=entry["title"],
            org_id=ORG_ID,
            deadline=detail["deadline"] or entry["deadline"],
            deadline_note=detail["deadline_note"] or entry["deadline_note"],
            posted_date=detail["posted_date"],
            apply_url=detail["apply_url"],
            location=LOCATION,
            description_text=detail["description_text"],
            language_requirements=[],  # not machine-readable on this ATS
            nationality_restrictions_status=restriction_status,
            nationality_restrictions_text=restriction_text,
            raw_snapshot_hash=snapshot_hash,
            evidence_id=evidence_id,
        )
        outcome = upsert_opportunity(store, posting)
        setattr(stats, outcome, getattr(stats, outcome) + 1)

    return stats
