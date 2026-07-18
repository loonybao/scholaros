/* Skills Radar — deterministic backend analytics; never recomputed here.
   Primary scope target_market; poor-fit vacancies excluded (kept in Archive). */

import { t } from "../i18n.js";
import { skillStatusLabel, skillTone } from "../labels.js";
import { badge, emptyState, esc, fetchJSON, pageHeader, panel } from "../ui.js";

const SCOPES = [["target_market", "skills.scope.target_market"],
  ["actionable", "skills.scope.actionable"], ["future_target", "skills.scope.future_target"]];

let state = { scope: "target_market", institution: null, open: null };
let data = null;

function bucket() {
  if (state.scope === "institution")
    return data.institutions[state.institution] || { total_opportunities: 0, skills: [] };
  return data.scopes[state.scope];
}

function scopeBar() {
  const radios = SCOPES.map(([k, lk]) =>
    `<label><input type="radio" name="scope" value="${k}" ${state.scope === k ? "checked" : ""}> ${t(lk)}</label>`).join("");
  const insts = Object.keys(data.institutions).sort();
  const opts = insts.map((org) =>
    `<option value="${esc(org)}" ${state.institution === org ? "selected" : ""}>${esc(data.institutions[org].name || org)}</option>`).join("");
  return `<div class="filter-bar">${radios}
    <label><input type="radio" name="scope" value="institution" ${state.scope === "institution" ? "checked" : ""}> ${t("skills.scope.institution")}</label>
    <select id="inst" aria-label="${t("skills.scope.institution")}">${opts}</select>
    <span class="result-count" id="cnt"></span></div>`;
}

function rows(b) {
  if (!b.skills.length) return emptyState(t("skills.none_scope"));
  const body = b.skills.map((s) => {
    const detail = state.open !== s.skill ? "" : `<tr><td colspan="6"><div class="skill-detail">
      <strong>${t("skills.evidence")}:</strong> ${esc(s.user_evidence || t("skills.evidence.none"))}<br>
      <strong>${t("skills.supporting")} (${s.supporting.length}):</strong>
      <ul>${s.supporting.map((o) => `<li>${esc(o.title)}</li>`).join("")}</ul>
      <a href="#/opportunities?skill=${encodeURIComponent(s.skill)}">${t("skills.browse_all")} →</a></div></td></tr>`;
    return `<tr class="clickable" data-skill="${esc(s.skill)}">
      <td><strong>${esc(s.label)}</strong></td>
      <td class="num">${s.required_count}</td><td class="num">${s.preferred_count}</td>
      <td class="num">${s.supporting.length}</td><td>${esc(s.user_level || t("common.none"))}</td>
      <td>${badge(skillStatusLabel(s.suggested_status), skillTone(s.suggested_status))}</td></tr>${detail}`;
  }).join("");
  return `<div class="table-wrap"><table>
    <tr><th>${t("skills.col.skill")}</th><th>${t("skills.col.required")}</th><th>${t("skills.col.preferred")}</th>
    <th>${t("skills.col.opportunities")}</th><th>${t("skills.col.level")}</th><th>${t("skills.col.status")}</th></tr>
    ${body}</table></div>`;
}

function draw(root) {
  const b = bucket();
  root.innerHTML = pageHeader(t("skills.title"), t("skills.subtitle")) +
    panel(t("skills.scope"), scopeBar()) + panel("", rows(b));
  root.querySelector("#cnt").textContent = t("skills.in_scope", { n: b.total_opportunities });
  root.querySelectorAll("input[name=scope]").forEach((el) => el.addEventListener("change", () => {
    state.scope = el.value;
    if (state.scope === "institution" && !state.institution)
      state.institution = Object.keys(data.institutions).sort()[0];
    draw(root);
  }));
  const inst = root.querySelector("#inst");
  if (inst) inst.addEventListener("change", () => { state.scope = "institution"; state.institution = inst.value; draw(root); });
  root.querySelectorAll("tr.clickable").forEach((tr) => tr.addEventListener("click", () => {
    state.open = state.open === tr.dataset.skill ? null : tr.dataset.skill; draw(root);
  }));
}

export default async function render(root) {
  data = await fetchJSON("/api/skills");
  if (state.scope === "institution" && !state.institution)
    state.institution = Object.keys(data.institutions).sort()[0];
  draw(root);
}
