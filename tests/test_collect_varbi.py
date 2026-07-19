"""S16: Varbi collector (KTH and other Nordic universities on the Varbi ATS).
Listing rows -> title/city/ISO-deadline; detail -> full description; three-way
discovery filter; per-institution org; idempotent. No network (fetch mocked)."""
from datetime import date
from pathlib import Path

from compass.collect import varbi
from compass.collect.base import classify_listing

FIXTURES = Path(__file__).parent / "fixtures" / "html"


def _listing() -> str:
    return (FIXTURES / "varbi_kth_listing.html").read_text(encoding="utf-8")


def _detail() -> str:
    return (FIXTURES / "varbi_kth_detail.html").read_text(encoding="utf-8")


def test_parse_listing_rows():
    by = {e["native_id"]: e for e in varbi.parse_listing(_listing())}
    assert len(by) == 5
    phd = by["954097"]
    assert "digital twins" in phd["title"].lower()
    assert phd["city"] == "Stockholm"
    assert phd["deadline"] == date(2026, 8, 14)
    assert phd["url"].startswith("https://kth.varbi.com/en/what:job/jobID:954097")


def test_three_way_filter():
    cats = {e["native_id"]: classify_listing(e["title"])[0]
            for e in varbi.parse_listing(_listing())}
    assert cats["954097"] == "accepted"       # Doctoral student -> phd
    assert cats["954145"] == "accepted"       # Postdoc
    assert cats["945964"] == "irrelevant"     # Registrator (admin)


def test_parse_detail_has_description():
    d = varbi.parse_detail(_detail())
    assert len(d["description_text"]) > 1000
    assert "Job description" in d["description_text"]


def _mock_fetch(url, **kwargs):
    return _detail() if "what:job" in url else _listing()


def test_collect_ingests_research_with_facts(cfg, store, monkeypatch):
    cfg.sources = {"sources": [{"id": "varbi", "rate_limit_seconds": 0,
        "institutions": [{"id": "kth", "name": "KTH Royal Institute of Technology",
                          "org_id": "org_kth", "base_url": "https://kth.varbi.com",
                          "country": "Sweden"}]}]}
    monkeypatch.setattr(varbi, "fetch", _mock_fetch)

    stats = varbi.collect(cfg, store)
    assert stats.created == 3 and stats.skipped_irrelevant == 2

    opps = {o.official.source_native_id: o for o in store.load_all("opportunity")}
    assert "kth-945964" not in opps                      # admin filtered
    phd = opps["kth-954097"]                             # digital twins doctoral student
    assert phd.official.position_type == "phd"
    assert phd.official.deadline == date(2026, 8, 14)
    assert phd.official.location == "Stockholm, Sweden"  # country last (geography gate)
    assert len(phd.official.description_text) > 1000
    assert phd.official.org_id == "org_kth"
    assert store.load("organisation", "org_kth").official.name.startswith("KTH")


def test_collect_idempotent(cfg, store, monkeypatch):
    cfg.sources = {"sources": [{"id": "varbi", "rate_limit_seconds": 0,
        "institutions": [{"id": "kth", "name": "KTH", "org_id": "org_kth",
                          "base_url": "https://kth.varbi.com", "country": "Sweden"}]}]}
    monkeypatch.setattr(varbi, "fetch", _mock_fetch)
    varbi.collect(cfg, store)
    n = len(list(store.load_all("opportunity")))
    stats2 = varbi.collect(cfg, store)
    assert stats2.created == 0 and stats2.unchanged == 3
    assert len(list(store.load_all("opportunity"))) == n
