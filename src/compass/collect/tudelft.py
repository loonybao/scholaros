"""TU Delft collector.

Source: careers.tudelft.nl (SAP SuccessFactors career site). The all-jobs
listing is server-rendered HTML (tr.data-row) and paginates via
/go/All-jobs/9021002/{startrow}/ in steps of 20; plain GET works without
cookies or anti-bot bypassing. An official RSS exists but carries only the 10
newest postings, so the HTML listing is the full discovery source.

TU Delft's SuccessFactors field customization (verified on live pages):
  listing: a.jobTitle-link (title + /job/<slug>/<reqid>/), span.jobFacility
           (faculty), span.jobShifttype (closing date '19 Jul 2026')
  detail:  itemprop/propertyid 'shift' = closing date, 'facility' = faculty,
           'businessunit' = stated salary range, span.jobdescription = body

Native ID = the numeric requisition id in the job URL. City comes from the
URL slug's leading token; the country comes from the org record
(org_tu_delft), never guessed.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional

from bs4 import BeautifulSoup

from ..config import Config
from ..store import Store, slugify
from .base import (
    CollectStats,
    RawPosting,
    audit_discovery,
    classify_listing,
    detect_mobility,
    detect_restrictions,
    ensure_organisation,
    fetch,
    save_evidence,
    save_snapshot,
    upsert_opportunity,
)

SOURCE_ID = "tudelft"
ORG_ID = "org_tu_delft"
BASE_URL = "https://careers.tudelft.nl"
LISTING_PATH = "/go/All-jobs/9021002/"
PAGE_SIZE = 20
MAX_PAGES = 15  # backstop (~121 jobs currently => 7 pages)

_JOB_HREF = re.compile(r"^/job/([^/]+)/(\d+)/?$")


def _parse_sf_date(text: str) -> Optional[date]:
    """'19 Jul 2026' -> date. Returns None when unparseable (never guessed)."""
    try:
        return datetime.strptime(text.strip(), "%d %b %Y").date()
    except ValueError:
        return None


def parse_listing(html: str) -> list[dict]:
    """Extract {native_id, url, title, faculty, deadline} from one page."""
    soup = BeautifulSoup(html, "html.parser")
    entries: list[dict] = []
    seen: set[str] = set()
    for row in soup.select("tr.data-row"):
        link = row.select_one("a.jobTitle-link")
        if link is None or not link.get("href"):
            continue
        m = _JOB_HREF.match(link["href"].strip())
        if not m:
            continue
        slug, req_id = m.group(1), m.group(2)
        if req_id in seen:
            continue
        seen.add(req_id)

        facility = row.select_one("span.jobFacility")
        closing = row.select_one("span.jobShifttype")
        entries.append(
            {
                "native_id": req_id,
                "slug": slug,
                "url": f"{BASE_URL}/job/{slug}/{req_id}/",
                "title": link.get_text(" ", strip=True),
                "faculty": facility.get_text(" ", strip=True) if facility else None,
                "deadline": _parse_sf_date(closing.get_text(strip=True)) if closing else None,
            }
        )
    return entries


def parse_detail(html: str) -> dict:
    """Extract official facts from a job detail page."""
    soup = BeautifulSoup(html, "html.parser")
    out: dict = {
        "deadline": None,
        "faculty": None,
        "salary_text": None,
        "description_text": "",
    }

    def prop(name: str) -> Optional[str]:
        el = soup.find(attrs={"data-careersite-propertyid": name})
        if el is None:
            return None
        text = el.get_text(" ", strip=True)
        return text or None

    shift = prop("shift")
    if shift:
        out["deadline"] = _parse_sf_date(shift)
    out["faculty"] = prop("facility")
    # 'businessunit' is TU Delft's stated salary range field.
    salary = prop("businessunit")
    if salary and "€" in salary:
        out["salary_text"] = f"{salary} per month (stated range)"

    body = soup.select_one("span.jobdescription")
    if body is not None:
        text = body.get_text("\n", strip=True)
        out["description_text"] = re.sub(r"\n{3,}", "\n\n", text)[:20000]
    return out


def _city_from_slug(slug: str) -> Optional[str]:
    city = slug.split("-", 1)[0]
    return city if city and city[:1].isupper() else None


def collect(cfg: Config, store: Store) -> CollectStats:
    stats = CollectStats()
    src_cfg = next(
        (s for s in cfg.sources.get("sources", []) if s["id"] == SOURCE_ID), {}
    )
    rate = float(src_cfg.get("rate_limit_seconds", 10))

    # Country from the canonical org record — organisational fact, not a guess.
    org_country = None
    if store.exists("organisation", ORG_ID):
        org_country = store.load("organisation", ORG_ID).official.country

    entries: list[dict] = []
    for page in range(MAX_PAGES):
        startrow = page * PAGE_SIZE
        path = LISTING_PATH if startrow == 0 else f"{LISTING_PATH}{startrow}/"
        url = f"{BASE_URL}{path}?q=&sortColumn=referencedate&sortDirection=desc"
        html = fetch(url, rate_limit_seconds=0 if page == 0 else rate)
        save_snapshot(cfg, SOURCE_ID, f"listing_p{page}", html)
        page_entries = parse_listing(html)
        if not page_entries:
            break
        entries.extend(page_entries)

    seen: set[str] = set()
    entries = [e for e in entries if not (e["native_id"] in seen or seen.add(e["native_id"]))]
    stats.fetched = len(entries)

    for entry in entries:
        category, _ptype, reason = classify_listing(entry["title"])
        if category != "accepted":
            audit_discovery(
                cfg, SOURCE_ID, entry["native_id"], entry["title"],
                entry["url"], category, reason,
            )
            if category == "candidate":
                stats.candidates += 1
            else:
                stats.skipped_irrelevant += 1
            continue
        stats.relevant += 1

        detail_html = fetch(entry["url"], rate_limit_seconds=rate)
        _, snapshot_hash = save_snapshot(
            cfg, SOURCE_ID, f"req{entry['native_id']}", detail_html
        )
        detail = parse_detail(detail_html)

        faculty = detail["faculty"] or entry["faculty"]
        faculty_org_id = None
        if faculty:
            faculty_org_id = ensure_organisation(
                store,
                f"org_tudelft_{slugify(faculty, max_len=50)}",
                f"{faculty} (TU Delft)",
                "faculty",
                ORG_ID,
                SOURCE_ID,
            )

        city = _city_from_slug(entry["slug"])
        location = (
            f"{city}, {org_country}" if city and org_country
            else (city or None)
        )

        restriction_status, restriction_text = detect_restrictions(
            detail["description_text"]
        )
        mobility_status, mobility_text = detect_mobility(detail["description_text"])
        evidence_id = save_evidence(
            cfg, SOURCE_ID, entry["native_id"], entry["url"],
            detail["description_text"],
        )

        posting = RawPosting(
            source=SOURCE_ID,
            source_native_id=entry["native_id"],
            canonical_url=entry["url"],
            title=entry["title"],
            org_id=ORG_ID,
            lab_org_id=faculty_org_id,
            deadline=detail["deadline"] or entry["deadline"],
            posted_date=None,  # not exposed on the SF pages
            apply_url=entry["url"],
            location=location,
            description_text=detail["description_text"],
            salary_text=detail["salary_text"],  # stated on the page, never inferred
            nationality_restrictions_status=restriction_status,
            nationality_restrictions_text=restriction_text,
            mobility_requirement_status=mobility_status,
            mobility_requirement_text=mobility_text,
            raw_snapshot_hash=snapshot_hash,
            evidence_id=evidence_id,
        )
        outcome = upsert_opportunity(store, posting)
        setattr(stats, outcome, getattr(stats, outcome) + 1)

    return stats
