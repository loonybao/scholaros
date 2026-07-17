"""Aalto University collector.

Source: the official aalto.fi English open-positions listing — server-rendered
Drupal HTML (the most stable official source; no structured public feed was
found). Listing entries are `div.aalto-listing__item--vacancy` blocks with
title/slug link, school, "Posted on" and "Closes on" <time datetime> stamps,
paginated via ?page=N. Detail pages carry an info container ("Application
closes on", "Unit", "Job category"), the body in `div.aalto-vacancy-content`,
and an external Workday apply link.

Native ID = the URL slug (stable). Position location is normalised from the
Workday apply URL's location segment when present (e.g.
".../job/Otaniemi-Espoo-Finland/...") — never guessed.
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
    detect_restrictions,
    ensure_organisation,
    fetch,
    save_evidence,
    save_snapshot,
    upsert_opportunity,
)

SOURCE_ID = "aalto"
ORG_ID = "org_aalto_university"
BASE_URL = "https://www.aalto.fi"
LISTING_URL = f"{BASE_URL}/en/open-positions"
MAX_PAGES = 10  # backstop; the pager currently ends around page 3


def _parse_time(el) -> tuple[Optional[date], Optional[str]]:
    """<time datetime="2026-07-25T12:00:00Z"> -> (date, 'HH:MM UTC'|None)."""
    if el is None or not el.get("datetime"):
        return None, None
    raw = el["datetime"]
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None, None
    note = None
    if "T" in raw:
        note = dt.strftime("%H:%M UTC") if raw.endswith(("Z", "+00:00")) else dt.strftime("%H:%M local")
    return dt.date(), note


def parse_listing(html: str) -> list[dict]:
    """Extract vacancy entries from one listing page."""
    soup = BeautifulSoup(html, "html.parser")
    entries: list[dict] = []
    for item in soup.select("div.aalto-listing__item--vacancy"):
        link = item.select_one("h2.aalto-listing__item-title a")
        if link is None or not link.get("href"):
            continue
        href = link["href"]
        slug = href.rstrip("/").split("/")[-1]
        title = link.get_text(" ", strip=True)

        school = None
        for meta in item.select(".aalto-listing__meta-item"):
            text = meta.get_text(" ", strip=True)
            if text and not text.lower().startswith("closes on"):
                school = text
                break

        posted, _ = _parse_time(item.select_one(".aalto-listing__date time"))
        deadline, deadline_note = None, None
        for meta in item.select(".aalto-listing__meta-item--grey"):
            if "closes on" in meta.get_text(" ", strip=True).lower():
                deadline, deadline_note = _parse_time(meta.find("time"))
                break

        entries.append(
            {
                "native_id": slug,
                "url": f"{BASE_URL}{href}" if href.startswith("/") else href,
                "title": title,
                "school": school,
                "posted_date": posted,
                "deadline": deadline,
                "deadline_note": deadline_note,
            }
        )
    return entries


def parse_detail(html: str) -> dict:
    """Extract official facts from an Aalto vacancy detail page."""
    soup = BeautifulSoup(html, "html.parser")
    out: dict = {
        "deadline": None,
        "deadline_note": None,
        "unit": None,
        "job_category": None,
        "description_text": "",
        "apply_url": None,
        "location": None,
    }

    for info in soup.select(".aalto-article__info-item"):
        title_el = info.select_one(".aalto-article__info-title")
        text_el = info.select_one(".aalto-article__info-text")
        if title_el is None or text_el is None:
            continue
        label = title_el.get_text(" ", strip=True).lower()
        if "closes on" in label:
            out["deadline"], out["deadline_note"] = _parse_time(text_el.find("time"))
        elif label == "unit":
            out["unit"] = text_el.get_text(" ", strip=True)
        elif "category" in label:
            out["job_category"] = text_el.get_text(" ", strip=True)

    body = soup.select_one("div.aalto-vacancy-content") or soup.select_one(
        "div.aalto-user-generated-content"
    )
    if body is not None:
        text = body.get_text("\n", strip=True)
        out["description_text"] = re.sub(r"\n{3,}", "\n\n", text)[:20000]

    apply_a = soup.select_one("a[href*='myworkdayjobs.com']")
    if apply_a is not None:
        out["apply_url"] = apply_a["href"].split("#")[0]
        out["location"] = _location_from_workday(out["apply_url"])
    return out


def _location_from_workday(url: str) -> Optional[str]:
    """'.../job/Otaniemi-Espoo-Finland/...' -> 'Espoo, Finland'. Never guess:
    return None when the segment does not name a country we can recognise."""
    m = re.search(r"/job/([^/]+)/", url)
    if not m:
        return None
    tokens = m.group(1).split("-")
    if len(tokens) < 2:
        return None
    country = tokens[-1]
    city = tokens[-2]
    if not country[:1].isupper() or not city[:1].isupper():
        return None
    return f"{city}, {country}"


def collect(cfg: Config, store: Store) -> CollectStats:
    stats = CollectStats()
    src_cfg = next(
        (s for s in cfg.sources.get("sources", []) if s["id"] == SOURCE_ID), {}
    )
    rate = float(src_cfg.get("rate_limit_seconds", 5))

    entries: list[dict] = []
    for page in range(MAX_PAGES):
        url = LISTING_URL if page == 0 else f"{LISTING_URL}?page={page}"
        html = fetch(url, rate_limit_seconds=0 if page == 0 else rate)
        save_snapshot(cfg, SOURCE_ID, f"listing_p{page}", html)
        page_entries = parse_listing(html)
        if not page_entries:
            break
        entries.extend(page_entries)
    # De-duplicate across pages (an entry can shift pages between fetches).
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
            cfg, SOURCE_ID, entry["native_id"][:60], detail_html
        )
        detail = parse_detail(detail_html)

        school = detail["unit"] or entry["school"]
        school_org_id = None
        if school:
            school_org_id = ensure_organisation(
                store,
                f"org_aalto_{slugify(school, max_len=50)}",
                f"{school} (Aalto University)",
                "faculty",
                ORG_ID,
                SOURCE_ID,
            )

        restriction_status, restriction_text = detect_restrictions(
            detail["description_text"]
        )
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
            lab_org_id=school_org_id,
            deadline=detail["deadline"] or entry["deadline"],
            deadline_note=detail["deadline_note"] or entry["deadline_note"],
            posted_date=entry["posted_date"],
            apply_url=detail["apply_url"],
            location=detail["location"],
            description_text=detail["description_text"],
            nationality_restrictions_status=restriction_status,
            nationality_restrictions_text=restriction_text,
            raw_snapshot_hash=snapshot_hash,
            evidence_id=evidence_id,
        )
        outcome = upsert_opportunity(store, posting)
        setattr(stats, outcome, getattr(stats, outcome) + 1)

    return stats
