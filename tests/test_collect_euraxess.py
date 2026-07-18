"""S13: EURAXESS collector — enriched listing parse (deadline, location,
research field, R1-R4 career stage), research-position classification, scoped
ingest with per-employer orgs, and idempotent re-runs. No network."""
from datetime import date
from pathlib import Path

from compass.collect import euraxess
from compass.models import _VALID_ID
from compass.rules import recompute_derived

FIXTURES = Path(__file__).parent / "fixtures" / "html"


def _html() -> str:
    return (FIXTURES / "euraxess_search.html").read_text(encoding="utf-8")


def test_parse_listing_extracts_enriched_fields():
    by_id = {e["native_id"]: e for e in euraxess.parse_listing(_html())}
    phd = by_id["999002"]
    assert phd["title"] == "PhD Position in Extended Reality for Human-Computer Interaction"
    assert phd["org_slug"] == "tu-delft"
    assert phd["offer_type"] == "JOB"
    assert phd["deadline"] == date(2026, 8, 30)         # from id-Application-Deadline
    assert "Delft" in phd["location"]                    # institution + city
    assert phd["location"].endswith("Netherlands")       # country LAST (geography gate reads last segment)
    assert phd["research_field"] == "Computer science"
    assert "R1" in phd["researcher_profile"]
    # a real card carried from the live page also has the structured fields
    real = by_id["454029"]
    assert real["deadline"] == date(2026, 8, 14)
    assert real["offer_type"] == "JOB" and "Italy" in real["location"]


def test_stage_maps_to_position_type():
    assert euraxess._stage_position_type("First Stage Researcher (R1)") == "phd"
    assert euraxess._stage_position_type("Recognised Researcher (R2)") == "postdoc"
    assert euraxess._stage_position_type("Leading Researcher (R4)") == "other"
    assert euraxess._stage_position_type("") is None


def test_org_id_is_namespaced_and_valid():
    assert euraxess._org_id("tu-delft", "TU Delft") == "org_euraxess_tu-delft"
    assert _VALID_ID.match(euraxess._org_id("", "Some Institute (X/Y)"))


def test_collect_ingests_research_with_full_facts(cfg, store, monkeypatch):
    cfg.sources = {"sources": [{"id": "euraxess", "keywords": ["extended reality"],
                                "max_pages": 1, "rate_limit_seconds": 0}]}
    monkeypatch.setattr(euraxess, "fetch", lambda *a, **k: _html())

    stats = euraxess.collect(cfg, store)
    assert stats.created >= 2                             # PhD + real research cards
    assert stats.skipped_irrelevant >= 1                 # the admin card (no R-profile)

    opps = {o.official.source_native_id: o for o in store.load_all("opportunity")}
    assert "999001" not in opps                          # admin filtered out
    phd = opps["999002"]
    assert phd.official.position_type == "phd"           # from the R1 profile
    assert phd.official.deadline == date(2026, 8, 30)    # real deadline captured
    assert "Delft" in (phd.official.location or "")
    assert "Research field: Computer science" in phd.official.description_text
    assert phd.official.org_id == "org_euraxess_tu-delft"
    assert store.load("organisation", "org_euraxess_tu-delft").manual.target is False
    # geography gate must recognise a European location (country is last)
    d = recompute_derived(phd, cfg.constraints, date(2026, 7, 19))
    assert not any("outside allowed regions" in r for r in d.eligibility_reasons)

    # a procedural-title real vacancy is accepted because it carries an R-profile
    real = opps["454029"]
    assert real.official.position_type in ("phd", "postdoc", "other")
    assert real.official.deadline == date(2026, 8, 14)


def test_collect_is_idempotent(cfg, store, monkeypatch):
    cfg.sources = {"sources": [{"id": "euraxess", "keywords": ["x"],
                                "max_pages": 1, "rate_limit_seconds": 0}]}
    monkeypatch.setattr(euraxess, "fetch", lambda *a, **k: _html())
    euraxess.collect(cfg, store)
    n = len(list(store.load_all("opportunity")))
    stats2 = euraxess.collect(cfg, store)
    assert stats2.created == 0 and stats2.unchanged >= 1
    assert len(list(store.load_all("opportunity"))) == n
