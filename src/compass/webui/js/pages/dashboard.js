/* Dashboard — personal research-career homepage. Seven focused sections;
   engineering detail (analysis queue, index internals) lives under System.
   Raw enum values are never shown — labels come from labels.js. */

import { fmtDateTime, fmtMonthYear } from "../format.js";
import { t } from "../i18n.js";
import {
  fitLabel, phaseLabel, prepText, skillStatusLabel, skillTone,
  timingLabel, timingTone, likelihoodLabel, likelihoodTone,
  valueLabel, valueTone,
} from "../labels.js";
import { badge, emptyState, esc, fetchJSON, panel } from "../ui.js";

/* ----- 1. personal status hero ----- */
function hero(h) {
  if (!h) return "";
  const phase = phaseLabel(h.current_phase);
  const dates = [
    ["dash.hero.expected", fmtMonthYear(h.expected_graduation)],
    ["dash.hero.prep_begins", fmtMonthYear(h.preparation_window.from)],
    ["dash.hero.active_period",
      `${fmtMonthYear(h.active_application_window.from)} – ${fmtMonthYear(h.active_application_window.to)}`],
  ].map(([k, v]) => `<div class="hero-date"><div class="k">${t(k)}</div><div class="v">${esc(v)}</div></div>`).join("");
  return `<div class="hero">
    <div class="hero-phase"><h1>${esc(phase)}</h1>
      ${badge(t("dash.hero.months_short", { n: Math.round(h.months_to_graduation) }), "info")}</div>
    <p class="hero-lede">${t("dash.hero.building")}</p>
    <div class="hero-noaction"><span aria-hidden="true">✓</span>${t("dash.hero.no_action")}</div>
    <div class="hero-dates">${dates}</div>
    <a class="btn secondary" href="#/roadmap">${t("dash.hero.view_roadmap")} →</a>
  </div>`;
}

/* ----- 2. current focus (max three cards) ----- */
function focus(skills) {
  const tm = (skills && skills.scopes && skills.scopes.target_market) || { skills: [] };
  const learn = tm.skills.filter((s) => s.suggested_status === "learn_next")
    .sort((a, b) => b.required_count - a.required_count).slice(0, 2);
  const cards = [`
    <div class="card">
      <h3>${t("dash.focus.thesis.title")}</h3>
      <div class="card-why">${t("dash.focus.thesis.body")}</div>
      <div class="card-foot">${t("dash.focus.thesis.milestone")}</div>
    </div>`];
  for (const s of learn) {
    const milestoneKey = s.skill === "statistics" ? "dash.focus.milestone_stat" : "dash.focus.milestone_py";
    const demand = s.preferred_count > 0
      ? t("dash.focus.required_pref_by", { n: s.required_count + s.preferred_count })
      : t("dash.focus.required_by", { n: s.required_count });
    cards.push(`
      <div class="card">
        <h3>${esc(s.label)}</h3>
        <div class="card-why">${esc(demand)}</div>
        <div class="card-row">${badge(t("dash.focus.status", { status: skillStatusLabel(s.suggested_status) }), skillTone(s.suggested_status))}</div>
        <div class="card-foot">${t(milestoneKey)} · <a href="#/skills">${t("dash.focus.open_skill")} →</a></div>
      </div>`);
  }
  return panel(t("dash.focus.title"), `<div class="card-grid">${cards.join("")}</div>`);
}

/* ----- 3. meaningful changes ----- */
function changes(items) {
  if (!items.length) return panel(t("dash.changes.title"), emptyState(t("dash.changes.none")));
  const rows = items.map((c) => {
    if (c.kind === "collector_issue")
      return `<div class="item-row">${badge(t("dash.changes.collector_issue", { source: c.source }), "danger")}</div>`;
    return `<div class="item-row">
      ${badge(t("dash.changes.signal"), "info")}
      ${c.recruitment_likelihood ? badge(likelihoodLabel(c.recruitment_likelihood), likelihoodTone(c.recruitment_likelihood)) : ""}
      <strong>${esc(c.title)}</strong>
      <span class="muted"> ${esc(c.org_name || "")}</span></div>`;
  }).join("");
  return panel(t("dash.changes.title"), rows);
}

/* ----- 4. target labs snapshot ----- */
function targetLabs(targets) {
  const labs = targets.filter((tg) => tg.org_type === "lab" || tg.org_type === "group").slice(0, 3);
  if (!labs.length) return "";
  const cards = labs.map((tg) => {
    const sig = (tg.latest_signals || [])[0];
    const prep = (tg.preparation_items || [])[0];
    const person = (tg.people || [])[0];
    return `<div class="card">
      <h3>${esc(tg.name)}</h3>
      <div class="card-row">
        ${tg.future_group_value ? badge(`${t("dash.labs.future_value")}: ${valueLabel(tg.future_group_value)}`, valueTone(tg.future_group_value)) : ""}
        ${tg.recruitment_likelihood ? badge(`${t("dash.labs.recruitment")}: ${likelihoodLabel(tg.recruitment_likelihood)}`, likelihoodTone(tg.recruitment_likelihood)) : ""}
      </div>
      <div class="card-meta"><strong>${t("dash.labs.latest_signal")}:</strong> ${sig ? esc(sig.title) : t("dash.labs.none_signal")}</div>
      <div class="card-meta"><strong>${t("dash.labs.prepare")}:</strong> ${prep ? esc(prepText(prep)) : t("dash.labs.none_prep")}</div>
      ${person ? `<div class="card-meta"><strong>${t("dash.labs.researcher")}:</strong> ${esc(person.name)}</div>` : ""}
    </div>`;
  }).join("");
  return panel(t("dash.labs.title"),
    `<div class="card-grid">${cards}</div><div class="card-foot"><a href="#/targets">${t("common.view_all")} →</a></div>`);
}

/* ----- 5. skills snapshot ----- */
function skillsSnapshot(skills) {
  const tm = (skills && skills.scopes && skills.scopes.target_market) || { skills: [] };
  const pick = (pred, n) => tm.skills.filter(pred).slice(0, n).map((s) => s.label);
  const strengths = pick((s) => s.suggested_status === "strength", 4);
  const learn = pick((s) => s.suggested_status === "learn_next", 4);
  const emerging = pick((s) => s.suggested_status === "optional" &&
    (s.preferred_count > 0 || !s.user_level || s.user_level === "none"), 3);
  if (!strengths.length && !learn.length && !emerging.length)
    return panel(t("dash.skills.title"), emptyState(t("dash.skills.none")));
  const col = (titleKey, list, tone) => `
    <div><h4>${t(titleKey)}</h4><div class="pill-row">
      ${list.length ? list.map((l) => badge(l, tone)).join("") : `<span class="empty-hint">${t("common.none")}</span>`}
    </div></div>`;
  return panel(t("dash.skills.title"), `
    <div class="detail-grid">
      ${col("dash.skills.strengths", strengths, "good")}
      ${col("dash.skills.learn_next", learn, "warn")}
      ${col("dash.skills.emerging", emerging, "info")}
    </div>
    <div class="card-foot"><a href="#/skills">${t("dash.skills.open")} →</a></div>`);
}

/* ----- 6. future-target evidence (compact cards) ----- */
function futureEvidence(rows) {
  if (!rows.length) return "";
  const cards = rows.slice(0, 4).map((r) => `
    <div class="card">
      <h3>${esc(r.title)}</h3>
      <div class="card-meta">${esc(r.org_name || r.org_id)}</div>
      <div class="card-row">
        ${r.fit_overall != null ? badge(`${t("dash.evidence.fit")}: ${r.fit_overall} (${fitLabel(r.fit_type)})`, "info") : ""}
        ${badge(`${t("dash.evidence.timing")}: ${timingLabel(r.timing_assessment)}`, timingTone(r.timing_assessment))}
      </div>
      <div class="card-foot">${t("dash.evidence.benchmark")}</div>
    </div>`).join("");
  return panel(t("dash.evidence.title"), `<div class="card-grid">${cards}</div>`);
}

/* ----- 7. compact system status ----- */
function systemStatus(health, changeCount) {
  const collectors = health.collectors || {};
  const issues = Object.values(collectors).filter((c) => c.consecutive_errors).length;
  const healthLine = issues
    ? badge(t("dash.status.issues", { n: issues }), "danger")
    : badge(t("dash.status.healthy"), "good");
  return panel("", `<div class="status-line">
    ${healthLine}
    <span><span class="k">${t("dash.status.last_update")}</span>${esc(fmtDateTime(health.index_rebuilt_at) || t("common.none"))}</span>
    <span><span class="k">${t("dash.status.new_items")}</span>${changeCount}</span>
    <a href="#/data-health" class="muted">${t("nav.data_health")} →</a>
  </div>`);
}

/* ----- optional action-required (only when there is something) ----- */
function actionRequired(dash) {
  const tasks = dash.manual_tasks || [];
  const opps = dash.action_required || [];
  if (!tasks.length && !opps.length) return "";
  const taskRows = tasks.map((tk) => `
    <div class="item-row">${badge(t("dash.action.pending"), "warn")} <strong>${esc(tk.title)}</strong>
      ${tk.due_date ? `<span class="muted"> · ${esc(tk.due_date)}</span>` : ""}</div>`).join("");
  const oppRows = opps.map((r) => `
    <div class="item-row"><strong>${esc(r.title)}</strong>
      <span class="muted"> ${esc(r.org_name || r.org_id)} · ${esc(r.deadline || "")}</span></div>`).join("");
  return panel("Action required", taskRows + oppRows);
}

export default async function render(root) {
  const [dash, health, skills, targetsResp] = await Promise.all([
    fetchJSON("/api/dashboard"), fetchJSON("/api/health"),
    fetchJSON("/api/skills"), fetchJSON("/api/targets"),
  ]);
  root.innerHTML = `
    <header class="page-header"><h1>${t("dash.title")}</h1></header>
    ${hero(dash.graduation_horizon)}
    ${actionRequired(dash)}
    ${focus(skills)}
    ${changes(dash.meaningful_changes || [])}
    ${targetLabs(targetsResp.targets || [])}
    ${skillsSnapshot(skills)}
    ${futureEvidence(dash.future_target_intel || [])}
    ${systemStatus(health, (dash.meaningful_changes || []).length)}
  `;
}
