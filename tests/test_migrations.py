from compass.migrations import load_migrations, upgrade_record


def test_migrations_load_in_version_order():
    migrations = load_migrations()
    versions = [v for v, _ in migrations]
    assert versions == sorted(versions)
    assert 1 in versions


def test_upgrade_record_stamps_version():
    record = {"schema_version": 0, "id": "opp_x"}
    upgraded, changed = upgrade_record(record)
    assert changed is True
    assert upgraded["schema_version"] >= 1


def test_upgrade_record_noop_when_current():
    migrations = load_migrations()
    latest = max(v for v, _ in migrations)
    record = {"schema_version": latest, "id": "opp_x"}
    _, changed = upgrade_record(record)
    assert changed is False


def test_upgrade_applies_only_pending_migrations():
    calls = []

    def fake_v2(record):
        calls.append(2)
        return record

    def fake_v3(record):
        calls.append(3)
        return record

    record = {"schema_version": 2}
    upgraded, changed = upgrade_record(record, [(1, lambda r: r), (2, fake_v2), (3, fake_v3)])
    assert changed is True
    assert calls == [3]
    assert upgraded["schema_version"] == 3
