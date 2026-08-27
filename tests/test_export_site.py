"""S19: static read-only dashboard (GitHub Pages). Self-contained HTML from the
same derived data; no network, no JS needed."""
from datetime import date, datetime, timezone

from compass.export_site import export_site, render_html
from compass.models import OpportunityAI, ScoreWithRationale
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


def _analysed(cfg, store, opp_id, title, fit_score, rec):
    """Seed one analysed opportunity with a controllable fit score."""
    opp = make_opportunity(opp_id=opp_id, title=title, url=f"https://e.org/{opp_id}")
    opp.ai = OpportunityAI(
        summary="s", fit_type="adjacent-methodological-fit",
        thematic_fit=ScoreWithRationale(score=fit_score, rationale="r"),
        methodological_fit=ScoreWithRationale(score=fit_score, rationale="r"),
        growth_value=ScoreWithRationale(score=fit_score, rationale="r"),
        strategic_value=ScoreWithRationale(score=fit_score, rationale="r"),
        recommendation=rec, confidence=0.9, model="m",
        prompt_version="fit_analysis_v1",
        analyzed_at=datetime(2026, 7, 17, tzinfo=timezone.utc),
        analysis_input_hash="h",
    )
    opp.derived = recompute_derived(opp, cfg.constraints, TODAY)
    store.save(opp, actor="manual")


def test_relevant_opportunities_ranked_by_fit(cfg, store):
    """Best fit first — a lower-fit 'apply' must not outrank a high-fit record."""
    store.save(make_organisation(), actor="manual")
    _analysed(cfg, store, "opp_low", "Low fit position", 30, "apply")
    _analysed(cfg, store, "opp_high", "High fit position", 90, "monitor")
    rebuild_index(cfg, store)
    # rank inside the browse list (the action section has its own ordering)
    listing = render_html(cfg, TODAY).split("Relevant opportunities", 1)[1]
    assert listing.index("High fit position") < listing.index("Low fit position")


def test_what_is_next_replaces_action_required(cfg, store):
    """Far from graduation nothing is pushed as an action; the page says so."""
    _seed(cfg, store)
    page = render_html(cfg, TODAY)
    assert "Action required" not in page
    assert "What&#x27;s next" in page or "What's next" in page
    assert "Nothing to act on yet" in page
