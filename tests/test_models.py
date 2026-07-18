from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from compass.models import (
    ENTITY_MODELS,
    Action,
    ActionManual,
    ActionSystem,
    Application,
    ApplicationSystem,
    Decision,
    DecisionBasis,
    DecisionSystem,
    Person,
    PersonOfficial,
    Signal,
    SignalOfficial,
    SkillProgress,
    SkillProgressSystem,
)
from conftest import make_opportunity, make_organisation

NOW = datetime(2026, 7, 17, tzinfo=timezone.utc)


def _sample(entity_type: str):
    if entity_type == "opportunity":
        return make_opportunity()
    if entity_type == "organisation":
        return make_organisation()
    if entity_type == "person":
        return Person(id="per_x", official=PersonOfficial(name="Test Person"))
    if entity_type == "signal":
        return Signal(
            id="sig_x",
            official=SignalOfficial(signal_type="paper", title="A paper"),
        )
    if entity_type == "decision":
        return Decision(
            id="dec_x",
            system=DecisionSystem(
                opportunity_id="opp_x",
                proposed="monitor",
                proposed_by="rules",
                proposed_at=NOW,
                basis=DecisionBasis(eligibility_gate="uncertain"),
            ),
        )
    if entity_type == "action":
        return Action(
            id="act_x",
            system=ActionSystem(action_type="research", created_by="human"),
            manual=ActionManual(title="Read PI's papers"),
        )
    if entity_type == "application":
        return Application(id="app_x", system=ApplicationSystem(opportunity_id="opp_x"))
    if entity_type == "skill_progress":
        return SkillProgress(id="skp_unity", system=SkillProgressSystem(skill_id="unity"))
    raise AssertionError(entity_type)


@pytest.mark.parametrize("entity_type", list(ENTITY_MODELS))
def test_round_trip(entity_type):
    model = ENTITY_MODELS[entity_type]
    entity = _sample(entity_type)
    dumped = entity.model_dump_json()
    restored = model.model_validate_json(dumped)
    assert restored == entity
    assert restored.entity_type == entity_type


def test_extra_fields_forbidden():
    opp = make_opportunity()
    data = opp.model_dump(mode="json")
    data["official"]["invented_fact"] = "nope"
    with pytest.raises(ValidationError):
        ENTITY_MODELS["opportunity"].model_validate(data)


def test_ai_layer_has_no_fact_fields():
    from compass.models import OpportunityAI

    fields = set(OpportunityAI.model_fields)
    for fact in ("deadline", "salary_text", "status", "canonical_url", "apply_url"):
        assert fact not in fields


@pytest.mark.parametrize(
    "bad_id",
    [
        "opp_..\\evil",
        "opp_../evil",
        "opp_a/b",
        "opp_a:b",
        "no_prefix",
        "opp_UPPER",
        "opp_",
        "C:\\absolute",
    ],
)
def test_unsafe_ids_rejected(bad_id):
    with pytest.raises(ValidationError):
        make_opportunity(opp_id=bad_id)


def test_apply_never_auto_finalized_at_model_level():
    with pytest.raises(ValidationError):
        DecisionSystem(
            opportunity_id="opp_x",
            proposed="apply",
            proposed_by="rules",
            proposed_at=NOW,
            basis=DecisionBasis(eligibility_gate="pass"),
            auto_finalized=True,
        )
