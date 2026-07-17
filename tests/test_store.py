from datetime import date

from conftest import make_opportunity


def test_save_and_load(store):
    opp = make_opportunity()
    store.save(opp, actor="manual")
    loaded = store.load("opportunity", opp.id)
    assert loaded.official.title == opp.official.title
    assert loaded.change_history[-1].actor == "manual"
    assert loaded.change_history[-1].fields_changed == ["*created*"]


def test_save_appends_change_history_with_field_diff(store):
    opp = make_opportunity()
    store.save(opp, actor="manual")

    loaded = store.load("opportunity", opp.id)
    loaded.official.deadline = date(2026, 8, 20)
    store.save(loaded, actor="collector:test")

    final = store.load("opportunity", opp.id)
    assert len(final.change_history) == 2
    assert final.change_history[-1].actor == "collector:test"
    assert "official.deadline" in final.change_history[-1].fields_changed


def test_save_noop_writes_nothing(store):
    opp = make_opportunity()
    store.save(opp, actor="manual")
    loaded = store.load("opportunity", opp.id)
    store.save(loaded, actor="manual")
    final = store.load("opportunity", opp.id)
    assert len(final.change_history) == 1


def test_identity_by_native_id(store):
    opp = make_opportunity()
    opp.official.source_native_id = "3110"
    store.save(opp, actor="manual")
    found = store.find_opportunity("3110", None)
    assert found is not None and found.id == opp.id


def test_identity_by_url_when_native_id_missing(store):
    opp = make_opportunity(url="https://example.org/jobs/42")
    store.save(opp, actor="manual")
    found = store.find_opportunity(None, "https://example.org/jobs/42")
    assert found is not None and found.id == opp.id


def test_identity_fingerprint_ignores_deadline(store):
    opp = make_opportunity(deadline=date(2026, 8, 3))
    opp.official.posted_date = date(2026, 7, 1)
    store.save(opp, actor="manual")
    # Same org/title/location/posted_date but DIFFERENT deadline and url:
    found = store.find_opportunity(
        source_native_id=None,
        canonical_url="https://example.org/jobs/other-url",
        org_id=opp.official.org_id,
        title="  doctoral researcher in HUMAN-CENTRED xr ",
        location="Tampere, Finland",
        posted_date="2026-07-01",
    )
    assert found is not None and found.id == opp.id


def test_diff_records_layer_fields_when_ai_layer_added(store):
    from datetime import datetime, timezone

    from compass.models import OpportunityAI, ScoreWithRationale

    opp = make_opportunity()
    store.save(opp, actor="manual")

    loaded = store.load("opportunity", opp.id)
    loaded.ai = OpportunityAI(
        summary="s",
        fit_type="exact-fit",
        thematic_fit=ScoreWithRationale(score=80, rationale="r"),
        methodological_fit=ScoreWithRationale(score=80, rationale="r"),
        growth_value=ScoreWithRationale(score=50, rationale="r"),
        strategic_value=ScoreWithRationale(score=50, rationale="r"),
        confidence=0.9,
        model="test-model",
        prompt_version="fit_analysis_v1",
        analyzed_at=datetime(2026, 7, 17, tzinfo=timezone.utc),
        analysis_input_hash="abc",
    )
    store.save(loaded, actor="ai")

    final = store.load("opportunity", opp.id)
    changed = final.change_history[-1].fields_changed
    assert "ai.summary" in changed and "ai.fit_type" in changed
    assert "ai" not in changed


def test_new_id_unique(store):
    opp = make_opportunity(opp_id="opp_doctoral-researcher")
    store.save(opp, actor="manual")
    next_id = store.new_id("opportunity", "Doctoral Researcher")
    assert next_id != opp.id
    assert next_id.startswith("opp_doctoral-researcher")
