/* Opportunity workspace — the S8a detail page. Read the full analysis for one
   vacancy and drive the personal application loop: create an application, set a
   personal status, keep private notes, or report a data issue. Only manual-layer
   fields, Application and Action records are ever written; official/ai/derived
   data is display-only and edits to it go through the review workflow, never in
   place. */

import { fmtDate } from "../format.js";
import { t } from "../i18n.js";
import {
  fitLabel, gateLabel, gateTone, recLabel, recTone, stageLabel,
  timingLabel, timingTone, valueLabel,
} from "../labels.js";
import { badge, esc, fetchJSON, sourceLink } from "../ui.js";
import { busy, guard, modalForm, patch, post } from "../write.js";

const LEVEL_TONE = { advanced: "good", intermediate: "info", beginner: "warn", none: "neutral" };
const USER_STATUS_TONE = {
  saved: "info", future_target: "info", considering: "warn", not_applying: "neutral",
};

function idFromHash() {
  const path = window.location.hash.replace(/^#\/?/, "").split("?")[0];
  return path.startsWith("opportunities/") ? decodeURIComponent(path.slice("opportunities/".length)) : null;
}

function scoreRow(labelKey, sc) {
  if (!sc) return "";
  return `<div class="score-row">
    <div class="score-head"><span>${t(labelKey)}</span><span class="score-num">${sc.score}</span></div>
    <div class="score-bar"><span style="width:${Math.max(0, Math.min(100, sc.score))}%"></span></div>
    ${sc.rationale ? `<div class="score-why">${esc(sc.rationale)}</div>` : ""}
  </div>`;
}

function skillPill(skill, levels) {
  const lvl = levels[skill] || "none";
  const tone = LEVEL_TONE[lvl] || "neutral";
  return `<span class="skill-pill">${esc(skill)} ${badge(t("detail.you_level", { level: t(`label.level.${lvl}`) }), tone)}</span>`;
}

function overview(d) {
  const o = d.official;
  const org = [o.org_name, o.lab_name].filter((x) => x && x !== o.org_id && x !== o.lab_org_id).join(" · ");
  const rows = [
    [t("detail.deadline"), o.deadline ? fmtDate(o.deadline) : t("common.none"), o.deadline_note],
    [t("detail.location"), o.location, null],
    [t("detail.salary"), o.salary_text, null],
    [t("detail.funding"), o.funding, null],
  ].filter(([, v]) => v).map(([k, v, note]) =>
    `<div class="kv"><div class="k">${esc(k)}</div><div class="v">${esc(v)}${note ? ` <span class="muted">(${esc(note)})</span>` : ""}</div></div>`).join("");
  return `<section class="panel detail-hero">
    <div class="detail-eyebrow">${esc(org || o.org_id)} · ${esc(o.position_type || "")}</div>
    <h1>${esc(o.title)}</h1>
    <div class="detail-badges">
      ${badge(gateLabel(d.derived.eligibility_gate), gateTone(d.derived.eligibility_gate))}
      ${d.derived.effective_recommendation ? badge(recLabel(d.derived.effective_recommendation), recTone(d.derived.effective_recommendation)) : ""}
      ${d.derived.timing_assessment ? badge(timingLabel(d.derived.timing_assessment), timingTone(d.derived.timing_assessment)) : ""}
      ${d.derived.fit_overall != null ? badge(`${t("detail.strategic")}: ${d.derived.fit_overall}`, "info") : ""}
    </div>
    <div class="kv-grid">${rows}</div>
    ${o.canonical_url ? `<div class="detail-source">${sourceLink(o.canonical_url, "detail.source")}</div>` : ""}
  </section>`;
}

function relevance(d) {
  if (!d.ai) return `<section class="panel"><h2>${t("detail.relevance")}</h2><div class="empty">${t("detail.not_analyzed")}</div></section>`;
  const a = d.ai;
  const list = (labelKey, arr, tone) => (arr && arr.length)
    ? `<div class="mini-block"><h4>${t(labelKey)}</h4><div class="pill-row">${arr.map((x) => badge(x, tone)).join("")}</div></div>` : "";
  return `<section class="panel">
    <h2>${t("detail.relevance")}</h2>
    ${a.summary ? `<p class="detail-summary">${esc(a.summary)}</p>` : ""}
    <div class="detail-badges">${badge(fitLabel(a.fit_type), "info")}${a.recommendation ? badge(recLabel(a.recommendation), recTone(a.recommendation)) : ""}</div>
    <div class="score-grid">
      ${scoreRow("detail.thematic", a.thematic_fit)}
      ${scoreRow("detail.methodological", a.methodological_fit)}
      ${scoreRow("detail.growth", a.growth_value)}
      ${scoreRow("detail.strategic", a.strategic_value)}
    </div>
    ${list("detail.why_match", (a.transferable_strengths || []).concat(a.matched_skills || []), "good")}
    ${list("detail.missing", a.missing_skills, "warn")}
    ${list("detail.risks", a.risks, "neutral")}
  </section>`;
}

function skills(d) {
  if (!d.ai) return "";
  const a = d.ai, lv = d.profile_levels || {};
  const block = (labelKey, arr) => (arr && arr.length)
    ? `<div class="mini-block"><h4>${t(labelKey)}</h4><div class="skill-row">${arr.map((s) => skillPill(s, lv)).join("")}</div></div>` : "";
  if (!(a.required_skills || []).length && !(a.preferred_skills || []).length) return "";
  return `<section class="panel"><h2>${t("detail.skills")}</h2>
    ${block("detail.required_skills", a.required_skills)}
    ${block("detail.preferred_skills", a.preferred_skills)}</section>`;
}

function statusPanel(d) {
  const m = d.manual;
  const app = d.application;
  const cur = m.user_status
    ? badge(t(`label.status.${m.user_status}`), USER_STATUS_TONE[m.user_status] || "neutral")
    : `<span class="muted">${t("detail.no_status")}</span>`;
  const appLine = app
    ? `<div class="status-app">${badge(stageLabel(app.stage), "info")}
        <a class="btn ghost sm" href="#/applications">${t("act.open_application")} →</a></div>`
    : `<button class="btn primary" data-act="create-app">${t("act.create_application")}</button>`;
  return `<section class="panel">
    <h2>${t("detail.my_status")}</h2>
    <div class="status-current">${t("opp.your_status")}: ${cur}</div>
    <div class="status-actions">
      ${appLine}
      <button class="btn ghost" data-act="future">${t("act.save_future")}</button>
      <button class="btn ghost" data-act="not-applying">${t("act.mark_not_applying")}</button>
      ${m.user_status ? `<button class="btn ghost" data-act="clear">${t("act.clear_status")}</button>` : ""}
    </div>
  </section>`;
}

function notesPanel(d) {
  return `<section class="panel">
    <h2>${t("detail.notes")}</h2>
    <textarea id="opp-notes" class="notes-area" placeholder="${t("detail.notes_placeholder")}">${esc(d.manual.notes || "")}</textarea>
    <div class="status-actions">
      <button class="btn secondary" data-act="save-note">${t("act.save_note")}</button>
      <button class="btn ghost" data-act="report-issue">${t("act.report_issue")}</button>
    </div>
  </section>`;
}

function evidencePanel(d) {
  const o = d.official;
  if (!o.description_text) return "";
  return `<details class="panel evidence"><summary>${t("detail.evidence")}</summary>
    <div class="evidence-body">${esc(o.description_text)}</div>
    ${o.apply_url ? `<div class="detail-source">${sourceLink(o.apply_url, "detail.source")}</div>` : ""}
  </details>`;
}

async function load(root) {
  const id = idFromHash();
  if (!id) { root.innerHTML = `<div class="empty">${t("opp.none")}</div>`; return; }
  let d;
  try {
    d = await fetchJSON(`/api/opportunities/${encodeURIComponent(id)}`);
  } catch {
    root.innerHTML = `<div class="empty">${t("opp.none")}<span class="empty-hint">${esc(id)}</span></div>`;
    return;
  }

  root.innerHTML = `
    <a class="back-link" href="#/opportunities">← ${t("detail.back")}</a>
    ${overview(d)}
    ${statusPanel(d)}
    ${relevance(d)}
    ${skills(d)}
    ${notesPanel(d)}
    ${evidencePanel(d)}`;

  const reload = () => load(root);
  const ver = d.updated_at;

  const setStatus = (el, body) => busy(el, () => guard(
    () => patch(`/api/opportunities/${encodeURIComponent(id)}/manual`, { expected_updated_at: ver, ...body }),
    { onDone: reload, success: t("act.saved") }));

  root.querySelector('[data-act="create-app"]')?.addEventListener("click", (e) =>
    busy(e.currentTarget, () => guard(() => post(`/api/opportunities/${encodeURIComponent(id)}/applications`), { onDone: reload, success: t("act.saved") })));
  root.querySelector('[data-act="future"]')?.addEventListener("click", (e) => setStatus(e.currentTarget, { user_status: "future_target" }));
  root.querySelector('[data-act="not-applying"]')?.addEventListener("click", (e) => setStatus(e.currentTarget, { user_status: "not_applying" }));
  root.querySelector('[data-act="clear"]')?.addEventListener("click", (e) => setStatus(e.currentTarget, { clear_user_status: true }));
  root.querySelector('[data-act="save-note"]')?.addEventListener("click", (e) =>
    setStatus(e.currentTarget, { notes: root.querySelector("#opp-notes").value }));

  root.querySelector('[data-act="report-issue"]')?.addEventListener("click", async () => {
    const vals = await modalForm({
      title: t("app.report_issue.title"),
      submitLabel: t("act.report_issue"),
      fields: [
        { name: "field", label: t("app.report_issue.field"), type: "text", placeholder: t("detail.deadline") },
        { name: "description", label: t("app.report_issue.desc"), type: "textarea" },
      ],
    });
    if (!vals || !vals.field || !vals.description) return;
    guard(() => post("/api/data-issues", { opportunity_id: id, field: vals.field, description: vals.description }),
      { success: t("act.saved") });
  });
}

export default async function render(root) {
  await load(root);
}
