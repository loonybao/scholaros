"""v4: ApplicationManual gains 'identified' pre-decision stage plus blockers,
internal_due_date and notes fields. Defaults apply; existing records need no
transformation — this stamps the version."""

VERSION = 4


def migrate(record: dict) -> dict:
    return record
