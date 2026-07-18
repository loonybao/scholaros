"""v3: OpportunityOfficial gains mobility_requirement_status/_text — MSCA-style
residence-history rules recorded separately from nationality/export-control
restrictions. Defaults apply; no data transformation needed."""

VERSION = 3


def migrate(record: dict) -> dict:
    return record
