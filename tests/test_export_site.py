"""S19: static read-only dashboard (GitHub Pages). Self-contained HTML from the
same derived data; no network, no JS needed."""
from datetime import date

from compass.export_site import export_site, render_html
from compass.index import rebuild_index
from compass.rules import recompute_derived
from conftest import TODAY, make_opportunity, make_organisation


def _seed(cfg, store):
    store.save(make_organisation(), actor="manual")
    opp = make_opportunity()
    opp.derived = recompute_derived(opp, cfg.constraints, TODAY)
    store.save(opp, actor="manual")
    rebuild_index(cfg, store)


def test_render_is_self_contained_html(cfg, store):
    _seed(cfg, store)
    html = render_html(cfg, TODAY)
    assert html.startswith("<!doctype html>")
    assert "<style>" in html and "<script" not in html   # inline CSS, no JS
    assert "Research Compass" in html
    assert "read-only" in html


def test_export_writes_index_and_nojekyll(cfg, store, tmp_path):
    _seed(cfg, store)
    out = tmp_path / "site"
    path = export_site(cfg, out, TODAY)
    assert path.is_file() and path.name == "index.html"
    assert (out / ".nojekyll").is_file()                  # Pages serves as-is
    assert path.read_text(encoding="utf-8").count("<!doctype html>") == 1


def test_no_raw_enums_leak(cfg, store):
    """Raw enum values are mapped to plain language, not shown verbatim."""
    _seed(cfg, store)
    html = render_html(cfg, TODAY)
    # internal enum strings must not appear raw in the page text
    for raw in ("timing_mismatch", "adjacent-methodological-fit", "eligibility_gate"):
        assert raw not in html
