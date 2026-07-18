"""v2: OpportunityAI gains provenance (analysis_provider/mode/status) and
advisory fields (transferable_strengths, funding_assessment, recommendation,
next_action). All new fields have defaults; existing records (which carry no
ai layer yet) need no data transformation — this stamps the version."""

VERSION = 2


def migrate(record: dict) -> dict:
    return record
