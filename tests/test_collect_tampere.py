from datetime import date
from pathlib import Path

from compass.collect.base import (
    classify_position_type,
    detect_restrictions,
    upsert_opportunity,
    RawPosting,
)
from compass.collect.tampere import canonical_url_for, parse_detail, parse_listing
from compass.store import normalize_url
from conftest import make_opportunity

FIXTURES = Path(__file__).parent / "fixtures" / "html"


def _listing_html() -> str:
    return (FIXTURES / "tampere_listing.html").read_text(encoding="utf-8")


def _detail_html() -> str:
    return (FIXTURES / "tampere_detail_3110.html").read_text(encoding="utf-8")


def test_parse_listing_extracts_entries():
    entries = parse_listing(_listing_html())
    by_id = {e["native_id"]: e for e in entries}
    assert set(by_id) == {"3110", "3123", "3124", "3105"}

    hti = by_id["3110"]
    assert hti["title"].startswith("Project Researcher (Human-technology interaction)")
    assert "Projektitutkija" not in hti["title"]  # Finnish half stripped
    assert hti["deadline"] == date(2026, 8, 3)
    assert "23:59" in hti["deadline_note"]


def test_parse_detail_extracts_official_facts():
    detail = parse_detail(_detail_html(), "3110")
    assert detail["deadline"] == date(2026, 8, 3)
    assert detail["posted_date"] == date(2026, 6, 25)
    assert "Pervasive Interaction Research Group" in detail["description_text"]
    assert detail["apply_url"] is not None
    assert "o=A_A" in detail["apply_url"]
    assert "rspvt" not in detail["apply_url"]  # session token stripped


def test_position_type_prefilter_is_field_agnostic():
    assert classify_position_type(
        "Project Researcher (Human-technology interaction), 2-5 positions"
    ) == "project_researcher"
    # Non-HCI doctoral position is still a research position (domain fit is S4):
    assert classify_position_type(
        "Doctoral Researcher (Computational Physics)"
    ) == "phd"


def test_classify_listing_three_way():
    from compass.collect.base import classify_listing

    cat, ptype, _ = classify_listing("Doctoral Researcher (Antenna Engineering)")
    assert cat == "accepted" and ptype == "phd"

    # Research-adjacent engineer titles must NOT be rejected by title alone:
    for title in [
        "Research Engineer",
        "Research Software Engineer",
        "XR Engineer",
        "HCI Engineer",
        "VR Software Developer",
    ]:
        cat, _, reason = classify_listing(title)
        assert cat == "candidate", (title, reason)

    # Confidently irrelevant:
    for title in [
        "Design, Simulation and Modelling Engineer for Advanced Semiconductor Packaging",
        "Financial Administrator",
        "Campus Facilities Manager",
    ]:
        cat, _, _ = classify_listing(title)
        assert cat == "irrelevant", title


def test_audit_log_written(cfg):
    from compass.collect.base import PREFILTER_RULE_VERSION, audit_discovery
    import json

    audit_discovery(
        cfg, "tampere", "9999", "XR Engineer", "https://example.org/x",
        "candidate", "research-adjacent role keyword",
    )
    path = cfg.paths.status / "discovery_audit.jsonl"
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    entry = json.loads(lines[-1])
    assert entry["title"] == "XR Engineer"
    assert entry["category"] == "candidate"
    assert entry["rule_version"] == PREFILTER_RULE_VERSION
    assert entry["url"] and entry["retrieved_at"] and entry["reason"]


def test_detect_restrictions_never_yields_stated():
    status, text = detect_restrictions(
        "Some projects may be subject to export control or sanctions."
    )
    assert status == "ambiguous"
    assert "export control" in text
    assert detect_restrictions("A normal HCI position.") == ("none_stated", None)


def test_normalize_url_ignores_param_order_and_session():
    a = normalize_url("https://tuni.rekrytointi.com/paikat/?jgid=3&jid=3110&o=A_RJ")
    b = normalize_url(
        "https://tuni.rekrytointi.com/paikat/?o=A_RJ&jid=3110&jgid=3&rspvt=abc&lang=en"
    )
    assert a == b


def _posting(**overrides) -> RawPosting:
    base = dict(
        source="tampere",
        source_native_id="3110",
        canonical_url=canonical_url_for("3110"),
        title="Project Researcher (Human-technology interaction), 2–5 positions",
        org_id="org_tampere_university",
        deadline=date(2026, 8, 3),
        posted_date=date(2026, 6, 25),
        location="Tampere, Finland",
        description_text="Long description",
        nationality_restrictions_status="ambiguous",
        nationality_restrictions_text="Posting mentions export control.",
    )
    base.update(overrides)
    return RawPosting(**base)


def test_upsert_creates_then_unchanged_then_updates(store):
    assert upsert_opportunity(store, _posting()) == "created"
    assert upsert_opportunity(store, _posting()) == "unchanged"

    # Deadline extension: must UPDATE the same record, never create a second.
    assert upsert_opportunity(store, _posting(deadline=date(2026, 8, 20))) == "updated"
    opps = list(store.load_all("opportunity"))
    assert len(opps) == 1
    assert opps[0].official.deadline == date(2026, 8, 20)
    assert any(
        "official.deadline" in e.fields_changed for e in opps[0].change_history
    )

    # Title correction must actually be written (regression: title was hashed
    # but not updated, silently dropping corrections).
    assert upsert_opportunity(
        store, _posting(deadline=date(2026, 8, 20), title="Project Researcher (HTI), corrected")
    ) == "updated"
    opp = list(store.load_all("opportunity"))[0]
    assert opp.official.title == "Project Researcher (HTI), corrected"


def test_upsert_merges_into_manual_record_via_url(store):
    manual = make_opportunity(
        opp_id="opp_tampere_manual",
        title="Project Researcher (Human-Technology Interaction), 2-5 positions",
        org_id="org_tampere_university",
        url="https://tuni.rekrytointi.com/paikat/?jgid=3&jid=3110&o=A_RJ",
    )
    store.save(manual, actor="manual")

    assert upsert_opportunity(store, _posting()) == "updated"
    opps = list(store.load_all("opportunity"))
    assert len(opps) == 1  # merged, not duplicated
    assert opps[0].id == "opp_tampere_manual"
    assert opps[0].official.source_native_id == "3110"
    assert opps[0].official.source == "tampere"


def test_fingerprint_never_merges_distinct_native_ids(store):
    """Two positions with identical generic titles and same posted date are
    distinct when their source native ids differ (regression: real Tampere run
    merged two 'Postdoctoral Research Fellow' postings)."""
    a = _posting(
        source_native_id="3134",
        canonical_url=canonical_url_for("3134"),
        title="Postdoctoral Research Fellow",
    )
    b = _posting(
        source_native_id="3125",
        canonical_url=canonical_url_for("3125"),
        title="Postdoctoral Research Fellow",
    )
    assert upsert_opportunity(store, a) == "created"
    assert upsert_opportunity(store, b) == "created"
    assert len(list(store.load_all("opportunity"))) == 2


def test_english_title_keeps_legitimate_slash():
    from compass.collect.tampere import english_title

    assert english_title(
        "Project Researcher (Human-technology interaction), 2–5 positions / "
        "Projektitutkija (Ihmisen ja teknologian vuorovaikutus), 2–5 tehtävää"
    ) == "Project Researcher (Human-technology interaction), 2–5 positions"

    assert english_title(
        "Research Assistant / M.Sc. thesis worker (Materials Science, Composite "
        "materials) / Tutkimusapulainen/Diplomityöntekijä (Materiaalioppi)"
    ) == "Research Assistant / M.Sc. thesis worker (Materials Science, Composite materials)"

    assert english_title("Doctoral Researcher") == "Doctoral Researcher"


def test_upsert_never_downgrades_stated_restriction(store):
    manual = make_opportunity(
        opp_id="opp_tampere_manual",
        url=canonical_url_for("3110"),
        nationality_restrictions_status="stated",
    )
    store.save(manual, actor="manual")
    upsert_opportunity(store, _posting(nationality_restrictions_status="none_stated"))
    opp = store.load("opportunity", "opp_tampere_manual")
    assert opp.official.nationality_restrictions_status == "stated"
