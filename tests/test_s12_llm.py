"""S12: live LLM analyze stage, exercised with an injected fake completion (no
network). Verifies the whitelist, ai-only automated writes, only-new/changed
selection, the per-run cap, the daily budget cap, and graceful handling of a
bad response."""
import json

import pytest

from compass.analysis_io import analysis_input_hash
from compass.analyze import analyze, pending_opportunity_ids
from compass.llm import LLMClient, LLMError, assert_whitelisted
from compass.rules import recompute_derived
from conftest import TODAY, make_opportunity, make_organisation


def _seed(cfg, store, n=1):
    cfg.taxonomy = {"programming": [{"id": "unity", "label": "Unity"}]}
    cfg.profile = {"skills": [{"id": "unity", "level": "advanced"}], "domains": ["hci"]}
    cfg.target_identity = {"statement": "Funded European PhD in HCI/XR."}
    cfg.models = {
        "api": {"model": "fake-model", "price_per_1k_tokens": 0.001},
        "limits": {"daily_cost_limit_usd": 1.0, "max_ai_items_per_run": 5},
        "context_whitelist": ["opportunity_official_text", "taxonomy",
                              "profile_skill_summary", "profile_domain_summary",
                              "target_identity_statement"],
    }
    cfg.api_key, cfg.api_base_url = "k", "http://localhost"
    store.save(make_organisation(), actor="manual")
    ids = []
    for i in range(n):
        opp = make_opportunity(opp_id=f"opp_x{i}", url=f"https://x.org/{i}")
        opp.derived = recompute_derived(opp, cfg.constraints, TODAY)
        store.save(opp, actor="manual")
        ids.append(opp.id)
    return ids


def _fake_completion(valid=True, capture=None):
    """Return a completion_fn that echoes a valid OpportunityAI per packet opp."""
    def fn(system, user):
        if capture is not None:
            capture.append(user)
        packet = json.loads(user)
        results = []
        for o in packet["opportunities"]:
            results.append({"id": o["id"], "analysis": {
                "summary": "auto summary", "fit_type": "adjacent-methodological-fit",
                "thematic_fit": {"score": 70, "rationale": "r"},
                "methodological_fit": {"score": 72, "rationale": "r"},
                "growth_value": {"score": 60, "rationale": "r"},
                "strategic_value": {"score": 65, "rationale": "r"},
                "required_skills": ["unity"], "recommendation": "monitor",
                "confidence": 0.8,
                "analysis_input_hash": o["analysis_input_hash"],
            }})
        body = json.dumps({"results": results})
        return (body if valid else "not json{{"), 1000
    return fn


def test_cli_analyze_and_run_registered():
    from pathlib import Path

    from compass import __main__ as m
    assert callable(m.cmd_analyze) and callable(m.cmd_run)
    src = Path(m.__file__).read_text(encoding="utf-8")
    assert '"analyze"' in src and '"run"' in src        # subcommands wired
    assert '"analyze": cmd_analyze' in src and '"run": cmd_run' in src


def test_assert_whitelisted_blocks_private_keys():
    with pytest.raises(LLMError):
        assert_whitelisted({"packet_type": "compass-analysis-packet",
                            "opportunities": [{"cv": "secret"}]})
    with pytest.raises(LLMError):
        assert_whitelisted({"packet_type": "something-else"})


def test_analyze_writes_ai_only_automated(cfg, store):
    ids = _seed(cfg, store, 1)
    client = LLMClient(cfg, completion_fn=_fake_completion())
    report = analyze(cfg, store, today=TODAY, client=client)
    assert report["imported"] == ids and not report["rejected"]
    opp = store.load("opportunity", ids[0])
    assert opp.ai is not None
    assert opp.ai.analysis_mode == "automated"          # automated provenance
    assert opp.ai.analysis_status == "provisional"      # never auto-final
    assert opp.official.title.startswith("Doctoral")    # official untouched
    assert opp.change_history[-1].actor == "ai"


def test_only_new_or_changed_are_pending(cfg, store):
    ids = _seed(cfg, store, 1)
    client = LLMClient(cfg, completion_fn=_fake_completion())
    analyze(cfg, store, today=TODAY, client=client)
    assert pending_opportunity_ids(cfg, store) == []    # nothing stale now
    # change the posting text -> the input hash changes -> pending again
    opp = store.load("opportunity", ids[0])
    opp.official.description_text = "materially different text"
    store.save(opp, actor="manual")
    assert pending_opportunity_ids(cfg, store) == ids


def test_sent_payload_is_whitelisted_packet_only(cfg, store):
    _seed(cfg, store, 1)
    captured: list = []
    client = LLMClient(cfg, completion_fn=_fake_completion(capture=captured))
    analyze(cfg, store, today=TODAY, client=client)
    sent = json.loads(captured[0])
    assert sent["packet_type"] == "compass-analysis-packet"
    # the private CV / notes are never in the payload
    blob = json.dumps(sent).lower()
    assert "vault" not in blob and "full_cv" not in blob


def test_per_run_cap(cfg, store):
    _seed(cfg, store, 5)
    cfg.models["limits"]["max_ai_items_per_run"] = 2
    client = LLMClient(cfg, completion_fn=_fake_completion())
    report = analyze(cfg, store, today=TODAY, client=client)
    assert report["pending"] == 5 and report["selected"] == 2
    assert len(report["imported"]) == 2


def test_skip_llm_calls_nothing(cfg, store):
    _seed(cfg, store, 1)
    def boom(system, user):
        raise AssertionError("LLM called under skip_llm")
    client = LLMClient(cfg, completion_fn=boom)
    report = analyze(cfg, store, skip_llm=True, today=TODAY, client=client)
    assert report["skipped"] and report["error"] == "skip_llm"
    assert store.load("opportunity", "opp_x0").ai is None


def test_not_configured_writes_nothing(cfg, store):
    _seed(cfg, store, 1)
    cfg.api_key = None                                  # no credentials
    client = LLMClient(cfg, completion_fn=_fake_completion())
    report = analyze(cfg, store, today=TODAY, client=client)
    assert report["skipped"] and report["error"] == "llm_not_configured"
    assert store.load("opportunity", "opp_x0").ai is None


def test_daily_budget_cap_stops(cfg, store):
    _seed(cfg, store, 1)
    client = LLMClient(cfg, completion_fn=_fake_completion())
    client.usage.add(TODAY, tokens=10_000, cost=2.0)    # already over the $1 cap
    report = analyze(cfg, store, today=TODAY, client=client)
    assert report["skipped"] and "cost limit" in report["error"]
    assert store.load("opportunity", "opp_x0").ai is None


def test_bad_response_leaves_ai_untouched(cfg, store):
    _seed(cfg, store, 1)
    client = LLMClient(cfg, completion_fn=_fake_completion(valid=False))
    report = analyze(cfg, store, today=TODAY, client=client)
    assert report["error"] and report["error"].startswith("invalid_response")
    assert store.load("opportunity", "opp_x0").ai is None
