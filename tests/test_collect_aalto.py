from datetime import date
from pathlib import Path

from compass.collect.aalto import (
    _location_from_workday,
    parse_detail,
    parse_listing,
)
from compass.collect.base import classify_listing

FIXTURES = Path(__file__).parent / "fixtures" / "html"


def _listing_html() -> str:
    return (FIXTURES / "aalto_listing.html").read_text(encoding="utf-8")


def _detail_html() -> str:
    return (FIXTURES / "aalto_detail_quantum.html").read_text(encoding="utf-8")


def test_parse_listing_extracts_entries():
    entries = parse_listing(_listing_html())
    by_id = {e["native_id"]: e for e in entries}
    assert "doctoral-students-theoretical-foundations-of-distributed-quantum-computing" in by_id
    assert "open-application-for-aalto-university" in by_id  # parsed; filtered later

    quantum = by_id["doctoral-students-theoretical-foundations-of-distributed-quantum-computing"]
    assert quantum["title"].startswith("Doctoral Students")
    assert quantum["url"].startswith("https://www.aalto.fi/en/open-positions/")

    lca = by_id["postdoctoral-researcher-advanced-life-cycle-assessment-lca-of-bio-based-processes-and-products"]
    assert lca["school"] == "School of Chemical Engineering"
    assert lca["deadline"] == date(2026, 7, 25)
    assert lca["posted_date"] == date(2026, 6, 29)


def test_listing_classification():
    entries = parse_listing(_listing_html())
    cats = {e["native_id"]: classify_listing(e["title"])[0] for e in entries}
    assert cats["doctoral-students-theoretical-foundations-of-distributed-quantum-computing"] == "accepted"
    assert cats["doctoral-researcher-in-fatigue-of-waam-structures"] == "accepted"
    assert cats["open-application-for-aalto-university"] == "irrelevant"
    assert cats["specialist-5"] == "irrelevant"


def test_parse_detail_extracts_official_facts():
    detail = parse_detail(_detail_html())
    assert detail["deadline"] == date(2026, 7, 31)
    assert detail["unit"] == "School of Science"
    assert "Doctoral Researchers" in detail["job_category"]
    assert "Department of Computer Science" in detail["description_text"]
    assert detail["apply_url"] is not None
    assert "myworkdayjobs.com" in detail["apply_url"]
    assert detail["location"] == "Espoo, Finland"


def test_location_from_workday_never_guesses():
    assert _location_from_workday(
        "https://aalto.wd3.myworkdayjobs.com/aalto/job/Otaniemi-Espoo-Finland/X"
    ) == "Espoo, Finland"
    assert _location_from_workday(
        "https://aalto.wd3.myworkdayjobs.com/aalto/job/Helsinki-Finland/X"
    ) == "Helsinki, Finland"
    assert _location_from_workday("https://example.org/no-job-segment") is None
