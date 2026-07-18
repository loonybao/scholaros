"""EURAXESS collector (S13) — the pan-European research-jobs aggregator.

EURAXESS lists ~9,000 vacancies, so this collector is scoped by KEYWORD (the
user's core research terms in config/sources.yaml) rather than crawling
everything — a keyword search returns a small, relevant set. Disabled by
default; enable + tune the keywords after reviewing the scope.

There is no plain-GET detail page (/jobs/<id> redirects to the search app), but
the server-rendered search cards are rich: each `article.ecl-content-item`
carries the title + /jobs/<id> native id, the employer + its stable profile
slug, posted date, the offer type (JOB / FUNDING / HOSTING), and a set of
`div.id-<Field>` blocks — Work Locations (country + institution + city),
Research Field, Researcher Profile (R1–R4 career stage), Funding Programme and
the Application Deadline. That is comparable to the university sources, so no
detail fetch is needed. The full posting text stays one click away at the
canonical URL.

Classification: EURAXESS tags every real vacancy with an R-profile, so a JOB
with an R-level is accepted as a research position (its career stage sets
position_type) — this avoids wrongly rejecting legitimate roles whose titles are
procedural or non-English. FUNDING/HOSTING offers and JOBs with neither an
R-level nor a research title are audited out. Domain fit (is it HCI/XR?) is left
to the analysis stage, not decided here.

Each employer becomes a namespaced `org_euraxess_<slug>` (org_type "other"),
never auto-marked target, so the Target Map stays clean. Official layer only.
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
    classify_position_type, detect_mobility, detect_restrictions,
    ensure_organisation, fetch, save_evidence, save_snapshot, upsert_opportunity,
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


def _parse_date(text: str) -> Optional[date]:
    text = (text or "").strip()
    for fmt in ("%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_deadline(text: Optional[str]) -> tuple[Optional[date], Optional[str]]:
    """'14 Aug 2026 - 23:59 (UTC)' -> (date(2026,8,14), '23:59 (UTC)')."""
    if not text:
        return None, None
    m = re.match(r"(\d{1,2}\s+\w+\s+\d{4})\s*(?:-\s*(.+))?$", text.strip())
    if not m:
        return None, None
    return _parse_date(m.group(1)), (m.group(2).strip() if m.group(2) else None)


def _stage_position_type(profile_text: Optional[str]) -> Optional[str]:
    """Lowest EURAXESS researcher profile -> position_type. R1 First Stage ~ PhD,
    R2 Recognised ~ postdoc, R3/R4 established/leading ~ senior (other)."""
    if not profile_text:
        return None
    levels = set(re.findall(r"R([1-4])", profile_text))
    if not levels:
        return None
    return {"1": "phd", "2": "postdoc", "3": "other", "4": "other"}[min(levels)]


def _org_id(slug: str, name: str) -> str:
    base = slug or re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    safe = re.sub(r"[^a-z0-9-]+", "-", base.lower()).strip("-")[:60] or "unknown"
    return f"org_euraxess_{safe}".rstrip("-")


def _field(art, id_class: str) -> Optional[str]:
    """Read a `div.id-<Field>` block, stripping its 'Label: ' prefix."""
    el = art.select_one(f"div.{id_class}")
    if el is None:
        return None
    txt = " ".join(el.get_text(" ", strip=True).split())
    txt = re.sub(r"^[^:]{0,40}:\s*", "", txt).strip()   # drop the leading label
    return txt or None


def _clean_location(work_locations: Optional[str], country: Optional[str]) -> Optional[str]:
    """Return a location string that ENDS with the country — the geography gate
    reads the last comma-segment as the country. EURAXESS lists 'Country,
    Institution, City', so we move the country to the end (else an Italian job
    would be read as country='<city>' and wrongly gated as outside Europe)."""
    segs: list[str] = []
    if work_locations:
        loc = re.sub(r"Number of offers:\s*\d+\s*,?\s*", "", work_locations).strip(" ,")
        segs = [s.strip() for s in loc.split(",") if s.strip()]
    if country and segs and segs[0].lower() == country.lower():
        segs = segs[1:]                       # drop the leading country duplicate
    if country:
        segs.append(country)                  # country last, for the gate
    return ", ".join(segs) if segs else country


def parse_listing(html: str) -> list[dict]:
    """One entry per result card, with the full structured fields."""
    soup = BeautifulSoup(html, "html.parser")
    entries: list[dict] = []
    seen: set[str] = set()
    for art in soup.select("article.ecl-content-item"):
        title_a = art.select_one("h3.ecl-content-block__title a")
        if not title_a:
            continue
        m = re.search(r"/jobs/(\d+)", title_a.get("href", ""))
        if not m or m.group(1) in seen:
            continue
        native_id = m.group(1)
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
                posted = _parse_date(pm.group(1))

        desc_el = art.select_one(".ecl-content-block__description")
        description = " ".join(desc_el.get_text(" ", strip=True).split()) if desc_el else ""

        offer_type, country = None, None
        parent = art.parent
        if parent is not None:
            for lab in parent.select(".ecl-content-block__label-item .ecl-label"):
                txt = lab.get_text(strip=True)
                if not txt:
                    continue
                if txt.upper() in _OFFER_LABELS:
                    offer_type = txt.upper()
                elif country is None:
                    country = txt

        deadline, deadline_note = _parse_deadline(_field(art, "id-Application-Deadline"))
        entries.append({
            "native_id": native_id, "title": title,
            "org_name": org_name, "org_slug": org_slug,
            "posted_date": posted, "description": description,
            "offer_type": offer_type,
            "location": _clean_location(_field(art, "id-Work-Locations"), country),
            "research_field": _field(art, "id-Research-Field"),
            "researcher_profile": _field(art, "id-Researcher-Profile"),
            "funding_programme": _field(art, "id-Funding-Programme"),
            "deadline": deadline, "deadline_note": deadline_note,
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
                break
            for entry in entries:
                seen_ids.add(entry["native_id"])
                stats.fetched += 1
                _ingest(cfg, store, entry, stats)
    return stats


def _ingest(cfg: Config, store: Store, entry: dict, stats: CollectStats) -> None:
    url = canonical_url_for(entry["native_id"])

    # FUNDING / HOSTING offers are not vacancies -> audited out.
    if (entry["offer_type"] or "JOB") != "JOB":
        audit_discovery(cfg, SOURCE_ID, entry["native_id"], entry["title"], url,
                        "irrelevant", f"offer type {entry['offer_type']} (not a job)")
        stats.skipped_irrelevant += 1
        return

    stage_ptype = _stage_position_type(entry["researcher_profile"])
    title_cat, title_ptype, title_reason = classify_listing(entry["title"])
    # A JOB with an R-profile IS a research position; else fall back to the title.
    if stage_ptype is None and title_cat != "accepted":
        audit_discovery(cfg, SOURCE_ID, entry["native_id"], entry["title"], url,
                        title_cat if title_cat == "candidate" else "irrelevant",
                        f"no researcher profile; {title_reason}")
        if title_cat == "candidate":
            stats.candidates += 1
        else:
            stats.skipped_irrelevant += 1
        return
    stats.relevant += 1
    position_type = title_ptype or stage_ptype or classify_position_type(entry["title"]) or "other"

    org_id = _org_id(entry["org_slug"], entry["org_name"])
    ensure_organisation(store, org_id, entry["org_name"], "other", None, SOURCE_ID)

    # Rich description: the snippet plus the structured card facts, so the
    # analysis stage has real context even without the full posting page.
    parts = [entry["description"]]
    if entry["research_field"]:
        parts.append(f"Research field: {entry['research_field']}")
    if entry["researcher_profile"]:
        parts.append(f"Researcher profile: {entry['researcher_profile']}")
    if entry["funding_programme"]:
        parts.append(f"Funding programme: {entry['funding_programme']}")
    description_text = "\n\n".join(p for p in parts if p)

    _, snapshot_hash = save_snapshot(
        cfg, SOURCE_ID, f"job_{entry['native_id']}", description_text or entry["title"])
    evidence_id = save_evidence(cfg, SOURCE_ID, entry["native_id"], url,
                                description_text or entry["title"])
    restriction_status, restriction_text = detect_restrictions(description_text)
    mobility_status, mobility_text = detect_mobility(description_text)

    posting = RawPosting(
        source=SOURCE_ID,
        source_native_id=entry["native_id"],
        canonical_url=url,
        title=entry["title"],
        org_id=org_id,
        position_type=position_type,
        deadline=entry["deadline"],
        deadline_note=entry["deadline_note"],
        posted_date=entry["posted_date"],
        location=entry["location"],
        description_text=description_text,
        nationality_restrictions_status=restriction_status,
        nationality_restrictions_text=restriction_text,
        mobility_requirement_status=mobility_status,
        mobility_requirement_text=mobility_text,
        raw_snapshot_hash=snapshot_hash,
        evidence_id=evidence_id,
    )
    outcome = upsert_opportunity(store, posting)
    setattr(stats, outcome, getattr(stats, outcome) + 1)
