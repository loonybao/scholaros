from datetime import date
from pathlib import Path

from compass.collect.base import classify_listing, upsert_opportunity, RawPosting
from compass.collect.tudelft import (
    _city_from_slug,
    parse_detail,
    parse_listing,
)

FIXTURES = Path(__file__).parent / "fixtures" / "html"


def _listing_html() -> str:
    return (FIXTURES / "tudelft_listing.html").read_text(encoding="utf-8")


def _detail_html() -> str:
    return (FIXTURES / "tudelft_detail_xr.html").read_text(encoding="utf-8")


def test_parse_listing_extracts_entries():
    entries = parse_listing(_listing_html())
    by_id = {e["native_id"]: e for e in entries}
    assert "1366984057" in by_id  # XR PhD
    assert "1364153857" in by_id  # Research Software Engineer

    xr = by_id["1366984057"]
    assert xr["title"] == "PhD Position eXtended Reality for Inclusive Automated Vehicle Interaction"
    assert xr["url"].startswith("https://careers.tudelft.nl/job/")
    assert xr["deadline"] == date(2026, 8, 30)

    # duplicate hrefs in a row (desktop+phone markup) must not duplicate entries
    assert len(entries) == len(by_id)


def test_listing_classification_three_way():
    entries = parse_listing(_listing_html())
    cats = {e["native_id"]: classify_listing(e["title"])[0] for e in entries}
    assert cats["1366984057"] == "accepted"      # PhD XR
    assert cats["1366984557"] == "accepted"      # Postdoc XR
    assert cats["1364153857"] == "candidate"     # Research Software Engineer
    assert cats["1364282157"] == "irrelevant"    # Open Hardware Project Officer


def test_parse_detail_extracts_official_facts():
    detail = parse_detail(_detail_html())
    assert detail["deadline"] == date(2026, 8, 30)
    assert detail["faculty"] == "Faculty of Civil Engineering and Geosciences"
    assert detail["salary_text"] is not None
    assert "3059" in detail["salary_text"] and "stated range" in detail["salary_text"]
    assert "Virtual Reality" in detail["description_text"]


def test_city_from_slug():
    assert _city_from_slug("Delft-PhD-Position-eXtended-Reality-2628-CD") == "Delft"
    assert _city_from_slug("lowercase-slug") is None


def test_deadline_change_updates_same_entity(store):
    """Requirement: changed fixture content must update the same entity."""
    def posting(deadline):
        return RawPosting(
            source="tudelft",
            source_native_id="1366984057",
            canonical_url="https://careers.tudelft.nl/job/Delft-PhD-XR/1366984057/",
            title="PhD Position eXtended Reality for Inclusive Automated Vehicle Interaction",
            org_id="org_tu_delft",
            deadline=deadline,
            location="Delft, Netherlands",
            description_text="desc",
        )

    assert upsert_opportunity(store, posting(date(2026, 8, 30))) == "created"
    assert upsert_opportunity(store, posting(date(2026, 8, 30))) == "unchanged"
    assert upsert_opportunity(store, posting(date(2026, 9, 15))) == "updated"
    opps = list(store.load_all("opportunity"))
    assert len(opps) == 1
    assert opps[0].official.deadline == date(2026, 9, 15)


def test_disappearance_from_listing_does_not_close(store):
    """A vacancy missing from one listing run keeps its status: collectors
    never close records; only deadline expiry (rules) or human/manual entry
    transitions status."""
    posting = RawPosting(
        source="tudelft",
        source_native_id="1366984057",
        canonical_url="https://careers.tudelft.nl/job/Delft-PhD-XR/1366984057/",
        title="PhD Position XR",
        org_id="org_tu_delft",
        deadline=date(2026, 8, 30),
        description_text="desc",
    )
    upsert_opportunity(store, posting)
    # Simulate a later run where this posting was NOT in the listing: nothing
    # touches the record; it must remain open.
    opp = list(store.load_all("opportunity"))[0]
    assert opp.official.status == "open"
