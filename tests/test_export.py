import pytest

from compass.export_vault import VaultExporter
from conftest import TODAY, make_opportunity, make_organisation


def test_export_writes_expected_files(cfg, store):
    store.save(make_organisation(), actor="manual")
    store.save(make_opportunity(), actor="manual")
    exporter = VaultExporter(cfg, store)
    count = exporter.export_all(TODAY)
    assert count == 3  # org + opp + dashboard

    dashboard = cfg.paths.vault_generated / "00-Dashboard.md"
    opp_page = cfg.paths.vault_generated / "01-Opportunities" / "opp_test.md"
    assert dashboard.is_file() and opp_page.is_file()

    text = opp_page.read_text(encoding="utf-8")
    assert "Doctoral Researcher in Human-Centred XR" in text
    assert "https://example.org/jobs/1" in text
    dash = dashboard.read_text(encoding="utf-8")
    assert "opp_test" in dash


def test_export_never_touches_notes(cfg, store):
    note = cfg.paths.vault_notes / "my-note.md"
    note.write_text("my private thoughts", encoding="utf-8")
    store.save(make_opportunity(), actor="manual")
    VaultExporter(cfg, store).export_all(TODAY)
    assert note.read_text(encoding="utf-8") == "my private thoughts"


def test_path_guard_raises_on_escape(cfg, store):
    exporter = VaultExporter(cfg, store)
    with pytest.raises(RuntimeError):
        exporter._safe_path("..", "notes", "evil.md")


def test_export_regenerates_cleanly(cfg, store):
    store.save(make_opportunity(), actor="manual")
    exporter = VaultExporter(cfg, store)
    exporter.export_all(TODAY)
    stale = cfg.paths.vault_generated / "01-Opportunities" / "opp_removed.md"
    stale.write_text("stale", encoding="utf-8")
    exporter.export_all(TODAY)
    assert not stale.exists()
