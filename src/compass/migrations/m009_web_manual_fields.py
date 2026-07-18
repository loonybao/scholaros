"""v9: web-editable manual fields — OpportunityManual.user_status and
ApplicationManual.portal_reference/documents_used. All optional with defaults;
no data transformation."""

VERSION = 9


def migrate(record: dict) -> dict:
    return record
