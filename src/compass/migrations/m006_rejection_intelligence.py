"""v6: structured rejection intelligence. OpportunityAI gains
rejection_reasons (controlled enum), future_group_value/_rationale (the lab's
value independent of this vacancy's decision), preferred_skills and
skill_evidence (required vs preferred separated, extraction evidence kept).
DecisionManual gains rejection_reasons. Defaults; no data transformation."""

VERSION = 6


def migrate(record: dict) -> dict:
    return record
