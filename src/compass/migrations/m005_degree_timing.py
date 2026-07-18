"""v5: OpportunityOfficial gains structured start/degree-timing facts
(start_date_value, start_date_negotiable, completed_degree_required_before_
start) for deterministic eligibility checks against the user's expected MSc
completion. Defaults (None = not stated); no data transformation."""

VERSION = 5


def migrate(record: dict) -> dict:
    return record
