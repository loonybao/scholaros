"""v10: introduce the SkillProgress entity (S8b). Additive — no existing record
changes shape, so this only advances the schema generation."""

VERSION = 10


def migrate(record: dict) -> dict:
    return record
