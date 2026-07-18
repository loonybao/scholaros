"""v7: SignalAI gains recruitment_likelihood (low/moderate/high),
recruitment_rationale, risks and the standard analysis provenance fields.
Defaults; no data transformation."""

VERSION = 7


def migrate(record: dict) -> dict:
    return record
