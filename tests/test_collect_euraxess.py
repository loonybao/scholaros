"""S13: EURAXESS collector — listing parse, three-way discovery filter, scoped
keyword ingest with per-employer orgs, and idempotent re-runs. No network: the
fetch is monkeypatched with a saved fixture."""
from datetime import date
from pathlib import Path

import pytest

from compass.collect import euraxess
from compass.collect.base import classify_listing
from compass.models import _VALID_ID

FIXTURES = Path(__file__).parent / "fixtures" / "html"


def _html() -> str:
    return (FIXTURES / "euraxess_search.html").read_text(encoding="utf-8")


def test_parse_listing_extracts_cards():
    by_id = {e["native_id"]: e for e in euraxess.parse_listing(_html())}
    # synthetic controlled cards
    phd = by_id["999002"]
    assert phd["title"] == "PhD Position in Extended Reality for Human-Computer Interaction"
    assert phd["org_name"] == "Delft University of Technology"
    assert phd["org_slug"] == "tu-delft"
    assert phd["country"] == "Netherlands"
    assert phd["posted_date"] == date(2026, 7, 12)
    assert "immersive" in phd["description"].lower()
    # a real card carried through from the live page
    assert "454029" in by_id
    assert by_id["454029"]["country"] == "Italy"


def test_three_way_filter():
    cats = {e["native_id"]: classify_listing(e["title"])[0]
            for e in euraxess.parse_listing(_html())}
    assert cats["999002"] == "accepted"       # PhD -> research position
    assert cats["999001"] == "irrelevant"     # Administrative Coordinator


def test_org_id_is_namespaced_and_valid():
    oid = euraxess._org_id("tu-delft", "Delft University of Technology")
    assert oid == "org_euraxess_tu-delft"
    assert _VALID_ID.match(oid)
    # falls back to the name when no slug
    assert _VALID_ID.match(euraxess._org_id("", "Some Institute (X/Y)"))


def test_collect_ingests_research_audits_rest(cfg, store, monkeypatch):
    cfg.sources = {"sources": [{"id": "euraxess", "keywords": ["extended reality"],
                                "max_pages": 1, "rate_limit_seconds": 0}]}
    monkeypatch.setattr(euraxess, "fetch", lambda *a, **k: _html())

    stats = euraxess.collect(cfg, store)
    assert stats.created >= 1
    assert stats.skipped_irrelevant >= 1                 # the admin card

    opps = {o.official.source_native_id: o for o in store.load_all("opportunity")}
    assert "999002" in opps                               # PhD ingested
    assert "999001" not in opps                           # admin NOT ingested
    phd = opps["999002"]
    assert phd.official.source == "euraxess"
    assert phd.official.org_id == "org_euraxess_tu-delft"
    assert phd.official.canonical_url == "https://euraxess.ec.europa.eu/jobs/999002"
    assert store.exists("organisation", "org_euraxess_tu-delft")
    # employer orgs are never auto-targeted (won't clutter the Target Map)
    assert store.load("organisation", "org_euraxess_tu-delft").manual.target is False

    # the irrelevant card is audited, not lost
    audit = (cfg.paths.status / "discovery_audit.jsonl").read_text(encoding="utf-8")
    assert "999001" in audit


def test_collect_is_idempotent(cfg, store, monkeypatch):
    cfg.sources = {"sources": [{"id": "euraxess", "keywords": ["x"],
                                "max_pages": 1, "rate_limit_seconds": 0}]}
    monkeypatch.setattr(euraxess, "fetch", lambda *a, **k: _html())
    euraxess.collect(cfg, store)
    n = len(list(store.load_all("opportunity")))
    stats2 = euraxess.collect(cfg, store)
    assert stats2.created == 0 and stats2.unchanged >= 1
    assert len(list(store.load_all("opportunity"))) == n   # no duplicates
