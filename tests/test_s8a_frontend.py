"""S8a frontend contract tests (zero-build UI). These read the shipped webui
files and assert: the new dynamic i18n key families are complete in every
locale; the opportunity-detail route is wired; the Opportunities/Archive split
(relevant cards vs full table) is in place; the editable application controls
exist; and every browser-side write targets one of the safe manual/Application/
Action endpoints (never an official/ai field)."""
import json
import re
from pathlib import Path

import pytest

WEBUI = Path(__file__).resolve().parents[1] / "src" / "compass" / "webui"
JS = WEBUI / "js"
LOCALES = WEBUI / "locales"


def _load(loc):
    return json.loads((LOCALES / f"{loc}.json").read_text(encoding="utf-8"))


EN, ZH_CN, ZH_MY = _load("en"), _load("zh-CN"), _load("zh-MY")


def _read(rel):
    return (JS / rel).read_text(encoding="utf-8")


# Dynamic key families introduced in S8a (t(prefix + variable)). Every value
# must exist in every locale or the UI would render a raw key at runtime.
S8A_FAMILIES = {
    "label.status": ["saved", "future_target", "considering", "not_applying", "not_reviewed"],
    "label.level": ["advanced", "intermediate", "beginner", "none"],
    "label.certainty": ["estimated", "confirmed"],
    "prep": ["strengthen", "learn", "portfolio", "monitor_person", "monitor_signal"],
    "prep.cat": ["skill", "method", "portfolio", "monitor"],
    "milestone": ["now", "prepare", "outreach", "active", "graduation"],
    "app.event": ["created", "preparing", "submitted", "corrected", "checklist", "stage"],
}


@pytest.mark.parametrize("locale_data", [EN, ZH_CN, ZH_MY], ids=["en", "zh-CN", "zh-MY"])
def test_s8a_dynamic_families_complete(locale_data):
    for prefix, values in S8A_FAMILIES.items():
        for v in values:
            assert f"{prefix}.{v}" in locale_data, f"missing {prefix}.{v}"


def test_milestone_and_certainty_keys_match_backend():
    """The keys rules.graduation_horizon emits must exist as locale keys, and
    the graduation milestone must interpolate {certainty}."""
    for k in ("milestone.now", "milestone.prepare", "milestone.outreach",
              "milestone.active", "milestone.graduation"):
        assert k in EN
    assert "{certainty}" in EN["milestone.graduation"]


def test_detail_route_wired():
    main = _read("main.js")
    assert "opportunity-detail" in main
    assert 'path.startsWith("opportunities/")' in main
    assert "navActive" in main  # detail highlights the Opportunities nav item


def test_opportunities_uses_relevant_cards_archive_uses_table():
    b = _read("pages/browser.js")
    # default (non-archive) page: relevant scope + card view linking to detail
    assert 'params.set("scope", "relevant")' in b
    assert "opp-card" in b and "#/opportunities/" in b
    # archive keeps the full audit table
    assert "archive ? table(rows) : cards(rows)" in b


def test_targets_collapses_institution_vacancies():
    tg = _read("pages/targets.js")
    assert "inst-vacancies" in tg
    assert "targets.show_all_inst" in tg
    assert "isRelevant" in tg  # relevant roles shown inline, rest disclosed


def test_applications_editable_controls_present():
    a = _read("pages/applications.js")
    for token in ('data-act="start"', 'data-act="toggle-mat"',
                  'data-act="submit"', "confirm_submitted", "documents_used"):
        assert token in a, f"missing application control: {token}"


def test_opportunity_detail_actions_present():
    d = _read("pages/opportunity_detail.js")
    for token in ('data-act="create-app"', 'data-act="future"',
                  'data-act="not-applying"', 'data-act="report-issue"',
                  "user_status"):
        assert token in d, f"missing detail action: {token}"


# The complete set of write endpoints the browser is allowed to call. Anything
# else (e.g. a PATCH straight at an official field) would be a boundary breach.
ALLOWED_WRITE_PATTERNS = [
    r"/api/opportunities/\$\{[^}]+\}/applications",  # create application (POST)
    r"/api/opportunities/\$\{[^}]+\}/manual",        # manual annotation (PATCH)
    r"/api/applications/\$\{[^}]+\}",                # application patch (PATCH)
    r"\$\{url\(id\)\}/correct-submission",           # audited submission correction (POST)
    r"\$\{url\(id\)\}/outcome",                      # record outcome (PATCH)
    r"/api/skills/\$\{[^}]+\}/progress",             # skill progress (PUT)
    r"/api/data-issues",                             # report issue -> action (POST)
    r"/api/actions",                                 # create action (POST)
]


def test_all_browser_writes_use_safe_endpoints():
    """Collect every post()/patch()/put() target across the UI and assert each
    matches an allowed safe endpoint (manual / Application / Action / skill)."""
    call = re.compile(r"""\b(?:post|patch|put)\(\s*[`"']([^`"']+)[`"']""")
    allowed = [re.compile(p) for p in ALLOWED_WRITE_PATTERNS]
    offenders = []
    for f in JS.rglob("*.js"):
        if f.name == "write.js":
            continue  # generic helper, not a call site
        for url in call.findall(f.read_text(encoding="utf-8")):
            if not any(rx.fullmatch(url) for rx in allowed):
                offenders.append(f"{f.name}: {url}")
    assert offenders == [], f"writes to non-whitelisted endpoints: {offenders}"


def test_write_helper_has_stale_and_error_handling():
    w = _read("write.js")
    assert "ApiError" in w
    assert "act.stale" in w        # 409 stale-write feedback
    assert "modalForm" in w        # confirmation dialogs for destructive/final acts


def test_correction_ui_present():
    a = _read("pages/applications.js")
    for token in ('data-act="correct"', "correct-submission",
                  "app.correct.reason", "app.correct.confirm", "correction_reason"):
        assert token in a, f"missing correction UI token: {token}"


def test_activity_history_present():
    a = _read("pages/applications.js")
    assert "app.history" in a and "timeline" in a and "eventLabel" in a


def test_checklist_is_optimistic_and_not_full_reload():
    """A checklist toggle must update in place (optimistic) and must not force a
    full-route reload on the success path — only stage changes reload."""
    a = _read("pages/applications.js")
    assert "setMaterialDom" in a                      # optimistic DOM update
    assert "btn.disabled = true" in a                 # no double submit while in flight
    fn = a[a.index("async function toggleMaterial"):a.index("activity history")]
    success_path = fn.split("} catch")[0]
    assert "reload()" not in success_path             # success path updates in place


def test_writes_show_busy_state():
    """Stage actions disable their button while saving (busy) so a slow write
    cannot be double-submitted."""
    a = _read("pages/applications.js")
    assert a.count("busy(") >= 4  # start / add-doc / submit / correct / editor
    assert "act.saving" in (WEBUI / "locales" / "en.json").read_text(encoding="utf-8")


def test_inline_editor_collapsed_by_default():
    """`.app-editor` sets display:flex, which would defeat the [hidden] toggle
    unless explicitly restored — the editor must stay collapsed until opened."""
    css = (WEBUI / "style.css").read_text(encoding="utf-8")
    assert ".app-editor[hidden]" in css and "display: none" in css
