/* Skills Radar — deterministic backend analytics (skills_radar), never
   recomputed in the frontend. Primary scope: target_market (poor-fit
   vacancies excluded by construction; they remain in Archive/Audit). */

import { emptyState, esc, fetchJSON, panel, statusBadge } from "../ui.js";

const SCOPES = [
  ["target_market", "Target market (main radar)"],
  ["actionable", "Actionable"],
  ["future_target", "Future targets"],
];

const STATUS_LABEL = {
  strength: "strength",
  maintain: "maintain",
  learn_next: "learn next",
  optional: "optional",
  not_relevant: "not relevant",
};

let state = { scope: "target_market", institution: null, openSkill: null };
let data = null;

function currentBucket() {
  if (state.scope === "institution")
    return data.institutions[state.institution] || { total_opportunities: 0, skills: [] };
  return data.scopes[state.scope];
}

function scopeBar() {
  const buttons = SCOPES.map(([key, label]) => `
    <label><input type="radio" name="scope" value="${key}"
      ${state.scope === key ? "checked" : ""}> ${esc(label)}</label>`).join("");
  const institutions = Object.keys(data.institutions).sort();
  const instOptions = institutions.map((org) =>
    `<option value="${esc(org)}" ${state.institution === org ? "selected" : ""}>
       ${esc(org.replace("org_", "").replace(/_/g, " "))}</option>`).join("");
  return `<div class="filter-bar">
    ${buttons}
    <label><input type="radio" name="scope" value="institution"
      ${state.scope === "institution" ? "checked" : ""}> institution:</label>
    <select id="inst-select">${instOptions}</select>
    <span class="result-count" id="scope-count"></span>
  </div>`;
}

function skillRows(bucket) {
  if (!bucket.skills.length)
    return emptyState("No skills recorded in this scope yet.");
  const rows = bucket.skills.map((s) => {
    const open = state.openSkill === s.skill;
    const detail = !open ? "" : `
      <tr><td colspan="6"><div class="skill-detail">
        <strong>Profile evidence:</strong> ${esc(s.user_evidence || "none recorded")}<br>
        <strong>Supporting opportunities (${s.supporting.length}):</strong>
        <ul>${s.supporting.map((o) =>
          `<li><a href="#/opportunities?skill=${encodeURIComponent(s.skill)}&q=${encodeURIComponent(o.title.slice(0, 30))}">${esc(o.title)}</a></li>`).join("")}
        </ul>
        <a href="#/opportunities?skill=${encodeURIComponent(s.skill)}">Browse all opportunities requiring ${esc(s.label)} →</a>
      </div></td></tr>`;
    return `
      <tr class="clickable" data-skill="${esc(s.skill)}">
        <td><strong>${esc(s.label)}</strong></td>
        <td class="num">${s.required_count}</td>
        <td class="num">${s.preferred_count}</td>
        <td class="num">${s.supporting.length}</td>
        <td>${esc(s.user_level || "—")}</td>
        <td>${statusBadge(STATUS_LABEL[s.suggested_status], "status-" + s.suggested_status)}</td>
      </tr>${detail}`;
  }).join("");
  return `<div class="table-wrap"><table>
    <tr><th>Skill</th><th>Required in</th><th>Preferred in</th>
    <th>Opportunities</th><th>Your level</th><th>Suggested status</th></tr>
    ${rows}</table></div>`;
}

function draw(root) {
  const bucket = currentBucket();
  root.innerHTML = `
    <header class="page-header">
      <h1>Skills Radar</h1>
      <div class="header-meta">Deterministic counts from skills_analytics — poor-fit vacancies are excluded from personal scopes but preserved in Archive/Audit.</div>
    </header>
    ${panel("Scope", scopeBar())}
    ${panel("Skills", skillRows(bucket))}
  `;
  root.querySelector("#scope-count").textContent =
    `${bucket.total_opportunities} opportunities in scope`;
  root.querySelectorAll("input[name=scope]").forEach((el) =>
    el.addEventListener("change", () => {
      state.scope = el.value;
      if (state.scope === "institution" && !state.institution)
        state.institution = Object.keys(data.institutions).sort()[0];
      draw(root);
    }));
  const sel = root.querySelector("#inst-select");
  if (sel) sel.addEventListener("change", () => {
    state.scope = "institution";
    state.institution = sel.value;
    draw(root);
  });
  root.querySelectorAll("tr.clickable").forEach((tr) =>
    tr.addEventListener("click", () => {
      state.openSkill = state.openSkill === tr.dataset.skill ? null : tr.dataset.skill;
      draw(root);
    }));
}

export default async function render(root) {
  data = await fetchJSON("/api/skills");
  if (state.scope === "institution" && !state.institution)
    state.institution = Object.keys(data.institutions).sort()[0];
  draw(root);
}
