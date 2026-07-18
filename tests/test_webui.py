"""UX product-shell contract tests: i18n coverage/fallback, raw-enum label
mapping, theme system, navigation hierarchy, and Analysis Queue removal from
the Dashboard. These read the shipped webui files (zero-build frontend)."""
import json
import re
from pathlib import Path

import pytest

WEBUI = Path(__file__).resolve().parents[1] / "src" / "compass" / "webui"
JS = WEBUI / "js"
LOCALES = WEBUI / "locales"


def _load(loc):
    return json.loads((LOCALES / f"{loc}.json").read_text(encoding="utf-8"))


EN = _load("en")
ZH_CN = _load("zh-CN")
ZH_MY = _load("zh-MY")


def _js_files():
    return list(JS.rglob("*.js"))


def _used_keys():
    """All t('key') / t("key") literal keys referenced across the frontend.
    Trailing-dot literals are dynamic prefixes (t('opp.filter.' + name)) and
    are checked separately as families."""
    pat = re.compile(r"""\bt\(\s*["']([^"']+)["']""")
    keys = set()
    for f in _js_files():
        keys |= set(pat.findall(f.read_text(encoding="utf-8")))
    return {k for k in keys if not k.endswith(".")}


# Dynamic key families (t(prefix + variable)) and their full value sets.
DYNAMIC_FAMILIES = {
    "opp.deadline": ["upcoming", "past", "none"],
    "opp.filter": ["any", "institution", "lab", "fit_type", "recommendation",
                   "eligibility_gate", "rejection_reason", "future_group_value",
                   "timing_assessment", "position_type", "deadline_status",
                   "status", "skill", "q", "q_placeholder"],
}


def test_all_used_keys_exist_in_english():
    """Every static t() key used in the UI exists in the English base."""
    missing = sorted(_used_keys() - set(EN))
    assert missing == [], f"t() keys missing from en.json: {missing}"


def test_dynamic_key_families_complete():
    for prefix, values in DYNAMIC_FAMILIES.items():
        for v in values:
            assert f"{prefix}.{v}" in EN, f"missing dynamic key {prefix}.{v}"


@pytest.mark.parametrize("loc,data", [("zh-CN", ZH_CN), ("zh-MY", ZH_MY)])
def test_translation_coverage_full(loc, data):
    """zh-CN and zh-MY provide every English key (100% coverage, no reliance on
    fallback for shipped keys). Coverage is reported for the delivery note."""
    missing = sorted(set(EN) - set(data))
    coverage = 100 * (len(EN) - len(missing)) / len(EN)
    print(f"\n{loc} coverage: {coverage:.1f}% ({len(EN) - len(missing)}/{len(EN)})")
    assert missing == [], f"{loc} missing keys: {missing}"


@pytest.mark.parametrize("loc,data", [("zh-CN", ZH_CN), ("zh-MY", ZH_MY)])
def test_no_orphan_keys(loc, data):
    """No locale key without an English counterpart (would never be reachable)."""
    orphans = sorted(set(data) - set(EN))
    assert orphans == [], f"{loc} orphan keys: {orphans}"


# Enum value lists that must have friendly labels in every locale.
ENUM_KEYS = {
    "label.timing": ["actionable_now", "prepare_for_current_cycle", "future_target",
                     "timing_mismatch", "timing_unknown"],
    "label.fit": ["exact-fit", "adjacent-methodological-fit", "poor-fit"],
    "label.rec": ["apply", "consider", "monitor", "reject"],
    "label.gate": ["pass", "uncertain", "fail"],
    "label.likelihood": ["high", "moderate", "low"],
    "label.value": ["high", "medium", "low"],
    "label.skill": ["strength", "maintain", "learn_next", "optional", "not_relevant"],
    "app.stage": ["identified", "preparing", "submitted", "monitoring",
                  "awaiting_response", "interview", "offered", "rejected", "withdrawn"],
    "phase": ["monitor_and_build", "prepare", "outreach_window", "active_application"],
}


@pytest.mark.parametrize("locale_data", [EN, ZH_CN, ZH_MY])
def test_every_raw_enum_has_a_label(locale_data):
    for prefix, values in ENUM_KEYS.items():
        for v in values:
            assert f"{prefix}.{v}" in locale_data, f"missing {prefix}.{v}"


def test_specific_timing_labels_match_spec():
    assert EN["label.timing.timing_unknown"] == "Start timing not stated"
    assert EN["label.timing.timing_mismatch"] == \
        "Not compatible with your current graduation timeline"
    assert EN["label.timing.future_target"] == "Future target"
    assert ZH_CN["label.timing.timing_unknown"] == "未说明入职时间"
    assert ZH_CN["label.timing.timing_mismatch"] == "与当前毕业时间规划不匹配"


def test_pages_use_label_helpers_not_raw_enums():
    """Dashboard and browser must render enums via labels.js, never inline."""
    for name in ("dashboard.js", "browser.js"):
        src = (JS / "pages" / name).read_text(encoding="utf-8")
        assert 'from "../labels.js"' in src


def test_i18n_has_english_fallback_and_dev_logging():
    src = (JS / "i18n.js").read_text(encoding="utf-8")
    assert "_en[key]" in src                       # falls back to English
    assert "console.warn" in src and "console.error" in src  # dev logging
    assert "localStorage" in src                   # persistence


def test_theme_system_three_modes_and_persistence():
    theme = (JS / "theme.js").read_text(encoding="utf-8")
    assert 'THEMES = ["system", "light", "dark"]' in theme
    assert "localStorage" in theme
    css = (WEBUI / "style.css").read_text(encoding="utf-8")
    assert '[data-theme="dark"]' in css
    assert '[data-theme="light"]' in css
    assert "prefers-color-scheme: dark" in css
    assert '[data-theme="system"]' in css          # System follows OS
    # No single duplicated Light/Dark stylesheet — one token system.
    assert len(list(WEBUI.glob("*.css"))) == 1


def test_navigation_hierarchy():
    main = (JS / "main.js").read_text(encoding="utf-8")
    for group in ("nav.group.today", "nav.group.explore", "nav.group.plan", "nav.group.system"):
        assert group in main
    for route in ("dashboard", "opportunities", "targets", "researchers", "signals",
                  "skills", "archive", "roadmap", "applications", "reviews",
                  "analysis-queue", "data-health", "settings"):
        assert f'"{route}"' in main or f"'{route}'" in main


def test_analysis_queue_absent_from_dashboard_present_in_system():
    dash = (JS / "pages" / "dashboard.js").read_text(encoding="utf-8")
    assert "analysis_queue" not in dash and "analysisQueue" not in dash
    queue_page = JS / "pages" / "analysis_queue.js"
    assert queue_page.is_file()
    assert "analysis_queue" in queue_page.read_text(encoding="utf-8")


def test_theme_no_fouc_bootstrap_in_html():
    html = (WEBUI / "index.html").read_text(encoding="utf-8")
    assert 'data-theme' in html and "localStorage.getItem" in html
