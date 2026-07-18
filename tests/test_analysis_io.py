import json

from compass.analysis_io import (
    analysis_input_hash,
    import_results,
    prepare_packet,
)
from conftest import make_opportunity

MODELS_CFG = {
    "context_whitelist": [
        "opportunity_official_text",
        "signal_official_text",
        "organisation_official_text",
        "person_official_text",
        "taxonomy",
        "profile_skill_summary",
        "profile_domain_summary",
        "target_identity_statement",
    ]
}


def _cfg(cfg):
    cfg.models = dict(MODELS_CFG)
    cfg.profile = {
        "education": {"degree": "MSc by Research"},
        "research_summary": "Human-centred XR.",
        "domains": ["human-centred-xr"],
        "skills": [{"id": "unity", "level": "advanced"}],
        "publications": {"first_author_journal_articles": 1},
        "private_note": "SHOULD NEVER LEAVE THE MACHINE",
    }
    cfg.target_identity = {"statement": "Human-centred XR researcher."}
    cfg.taxonomy = {"programming": [{"id": "unity", "label": "Unity"}]}
    return cfg


def _analysis(hash_value: str) -> dict:
    return {
        "summary": "A strong HCI/XR match.",
        "fit_type": "exact-fit",
        "thematic_fit": {"score": 90, "rationale": "core overlap"},
        "methodological_fit": {"score": 85, "rationale": "user studies"},
        "growth_value": {"score": 60, "rationale": "new methods"},
        "strategic_value": {"score": 70, "rationale": "target country"},
        "required_skills": ["unity"],
        "matched_skills": ["unity"],
        "missing_skills": [],
        "transferable_strengths": ["multiplayer prototyping"],
        "eligibility_flags": [],
        "risks": ["project assignment uncertain"],
        "funding_assessment": "Posting text implies salaried position.",
        "recommendation": "apply",
        "next_action": "Verify posting and draft motivation letter.",
        "confidence": 0.85,
        "analysis_input_hash": hash_value,
    }


def test_packet_contains_only_whitelisted_content(cfg, store):
    cfg = _cfg(cfg)
    opp = make_opportunity()
    store.save(opp, actor="manual")
    packet = prepare_packet(cfg, store, [opp.id])
    dumped = json.dumps(packet)
    assert "SHOULD NEVER LEAVE THE MACHINE" not in dumped
    assert packet["opportunities"][0]["id"] == opp.id
    assert packet["opportunities"][0]["analysis_input_hash"]
    assert packet["prompt_version"] == "fit_analysis_v1"


def test_import_writes_ai_layer_only(cfg, store, tmp_path):
    cfg = _cfg(cfg)
    opp = make_opportunity()
    opp.manual.notes = "my precious note"
    store.save(opp, actor="manual")

    h = analysis_input_hash(cfg, store.load("opportunity", opp.id))
    result = {"results": [{"id": opp.id, "analysis": _analysis(h)}]}
    rf = tmp_path / "result.json"
    rf.write_text(json.dumps(result), encoding="utf-8")

    report = import_results(cfg, store, rf, model="claude-fable-5")
    assert report["imported"] == [opp.id]
    assert report["rejected"] == []

    loaded = store.load("opportunity", opp.id)
    assert loaded.ai is not None
    assert loaded.ai.analysis_provider == "interactive_claude"
    assert loaded.ai.analysis_mode == "manual_assisted"
    assert loaded.ai.analysis_status == "provisional"
    assert loaded.ai.model == "claude-fable-5"
    assert loaded.ai.prompt_version == "fit_analysis_v1"
    # official/manual untouched:
    assert loaded.manual.notes == "my precious note"
    assert loaded.official.title == opp.official.title
    # change history recorded with actor ai:
    assert loaded.change_history[-1].actor == "ai"
    assert any(f.startswith("ai.") for f in loaded.change_history[-1].fields_changed)


def test_import_rejects_stale_hash(cfg, store, tmp_path):
    cfg = _cfg(cfg)
    opp = make_opportunity()
    store.save(opp, actor="manual")
    result = {"results": [{"id": opp.id, "analysis": _analysis("deadbeef")}]}
    rf = tmp_path / "r.json"
    rf.write_text(json.dumps(result), encoding="utf-8")
    report = import_results(cfg, store, rf, model="m")
    assert report["imported"] == []
    assert "stale" in report["rejected"][0]


def test_import_rejects_fact_smuggling(cfg, store, tmp_path):
    cfg = _cfg(cfg)
    opp = make_opportunity()
    store.save(opp, actor="manual")
    h = analysis_input_hash(cfg, store.load("opportunity", opp.id))
    bad = _analysis(h)
    bad["salary_text"] = "EUR 9999"
    result = {"results": [{"id": opp.id, "analysis": bad}]}
    rf = tmp_path / "r.json"
    rf.write_text(json.dumps(result), encoding="utf-8")
    report = import_results(cfg, store, rf, model="m")
    assert report["imported"] == []
    assert "forbidden" in report["rejected"][0]
    assert store.load("opportunity", opp.id).ai is None


def test_import_rejects_invalid_schema(cfg, store, tmp_path):
    cfg = _cfg(cfg)
    opp = make_opportunity()
    store.save(opp, actor="manual")
    h = analysis_input_hash(cfg, store.load("opportunity", opp.id))
    bad = _analysis(h)
    bad["thematic_fit"] = {"score": 250, "rationale": "out of range"}
    result = {"results": [{"id": opp.id, "analysis": bad}]}
    rf = tmp_path / "r.json"
    rf.write_text(json.dumps(result), encoding="utf-8")
    report = import_results(cfg, store, rf, model="m")
    assert report["imported"] == []
    assert "validation failed" in report["rejected"][0]


def test_import_rejects_unknown_opportunity(cfg, store, tmp_path):
    cfg = _cfg(cfg)
    result = {"results": [{"id": "opp_nope", "analysis": _analysis("x")}]}
    rf = tmp_path / "r.json"
    rf.write_text(json.dumps(result), encoding="utf-8")
    report = import_results(cfg, store, rf, model="m")
    assert report["rejected"] == ["opp_nope: unknown opportunity"]
