/* Opportunity Browser + Archive/Audit. Read-only, server-filtered.
   Rejected and poor-fit records are always reachable here — nothing is ever
   deleted or hidden from the audit view. */

import {
  badge, emptyState, esc, fetchJSON, gateBadge, panel, recommendationBadge,
} from "../ui.js";

const FILTERS = [
  ["org_id", "Institution"],
  ["lab_org_id", "Lab / unit"],
  ["fit_type", "Fit type", ["exact-fit", "adjacent-methodological-fit", "poor-fit"]],
  ["recommendation", "Proposal", ["apply", "consider", "monitor", "reject"]],
  ["eligibility_gate", "Gate", ["pass", "uncertain", "fail"]],
  ["rejection_reason", "Rejection reason", [
    "poor_research_fit", "eligibility_mismatch", "degree_timing_mismatch",
    "career_stage_mismatch", "unpaid_or_self_funded", "language_requirement",
    "mobility_or_location_constraint", "deadline_passed", "user_not_interested",
  ]],
  ["future_group_value", "Group value", ["high", "medium", "low"]],
  ["timing_assessment", "Timing", [
    "actionable_now", "prepare_for_current_cycle", "future_target",
    "timing_mismatch", "timing_unknown",
  ]],
  ["position_type", "Career stage", [
    "phd", "postdoc", "project_researcher", "research_assistant", "other",
  ]],
  ["deadline_status", "Deadline", ["upcoming", "past", "none"]],
  ["status", "Status", ["open", "closed", "expired", "unknown"]],
];

function queryFilters() {
  const hashQuery = window.location.hash.split("?")[1] || "";
  return Object.fromEntries(new URLSearchParams(hashQuery).entries());
}

function filterBar(active, orgs, labs, skills) {
  const select = (name, label, options) => {
    const opts = ['<option value="">any</option>'].concat(
      options.map(([v, t]) =>
        `<option value="${esc(v)}" ${active[name] === v ? "selected" : ""}>${esc(t)}</option>`));
    return `<label>${esc(label)} <select data-filter="${name}">${opts.join("")}</select></label>`;
  };
  const parts = FILTERS.map(([name, label, opts]) => {
    if (name === "org_id") return select(name, label, orgs);
    if (name === "lab_org_id") return select(name, label, labs);
    return select(name, label, (opts || []).map((o) => [o, o]));
  });
  parts.push(select("skill", "Required/preferred skill", skills.map((s) => [s, s])));
  parts.push(`<label>Search <input type="text" data-filter="q"
    value="${esc(active.q || "")}" placeholder="title contains…"></label>`);
  parts.push(`<span class="result-count" id="browse-count"></span>`);
  return `<div class="filter-bar">${parts.join("")}</div>`;
}

function resultTable(rows) {
  if (!rows.length)
    return emptyState("No records match the current filters.",
      "Clear filters to see the full audit database.");
  const body = rows.map((r) => `
    <tr>
      <td><a href="${esc(r.canonical_url)}" target="_blank" rel="noopener">${esc(r.title)}</a></td>
      <td>${esc((r.org_name || r.org_id || "").replace(" (Aalto University)", "").replace(" (TU Delft)", ""))}</td>
      <td>${esc(r.position_type)}</td>
      <td class="num">${esc(r.deadline || "—")} <span class="card-org">(${esc(r.deadline_status)})</span></td>
      <td>${gateBadge(r.eligibility_gate)}</td>
      <td class="num">${r.fit_overall ?? "—"}</td>
      <td>${recommendationBadge(r) || "—"}</td>
      <td>${r.timing_assessment ? badge(r.timing_assessment,
        r.timing_assessment === "actionable_now" ? "pass"
        : r.timing_assessment.startsWith("timing_") ? "uncertain" : "none") : "—"}</td>
      <td>${r.rejection_reasons.map((x) => badge(x, "none")).join(" ") || "—"}</td>
      <td>${r.future_group_value ? badge(`group: ${r.future_group_value}`, r.future_group_value === "high" ? "pass" : "none") : "—"}</td>
    </tr>`).join("");
  return `<div class="table-wrap"><table>
    <tr><th>Opportunity</th><th>Organisation</th><th>Stage</th><th>Deadline</th>
    <th>Gate</th><th>Fit</th><th>Proposal</th><th>Timing</th><th>Rejection reasons</th><th>Group value</th></tr>
    ${body}</table></div>`;
}

async function load(root, archive) {
  const active = queryFilters();
  const qs = new URLSearchParams(active).toString();
  const data = await fetchJSON("/api/opportunities" + (qs ? `?${qs}` : ""));
  const rows = data.opportunities;

  const orgs = [...new Map(rows.map((r) => [r.org_id, r.org_name || r.org_id])).entries()];
  const labs = [...new Map(rows.filter((r) => r.lab_org_id)
    .map((r) => [r.lab_org_id, r.lab_name || r.lab_org_id])).entries()];
  const skills = [...new Set(rows.flatMap((r) =>
    r.required_skills.concat(r.preferred_skills)))].sort();

  root.innerHTML = `
    <header class="page-header">
      <h1>${archive ? "Archive / Full Audit" : "Opportunity Browser"}</h1>
      <div class="header-meta">${archive
        ? "Every collected record — poor-fit and rejected included. Nothing is ever deleted."
        : "Read-only browser over the full audit database."}</div>
    </header>
    ${panel("Filters", filterBar(active, orgs, labs, skills))}
    ${panel("Results", resultTable(rows))}
  `;
  root.querySelector("#browse-count").textContent = `${data.count} record(s)`;

  root.querySelectorAll("[data-filter]").forEach((el) => {
    const apply = () => {
      const params = new URLSearchParams(window.location.hash.split("?")[1] || "");
      if (el.value) params.set(el.dataset.filter, el.value);
      else params.delete(el.dataset.filter);
      const base = archive ? "#/archive" : "#/opportunities";
      window.location.hash = `${base}?${params.toString()}`;
    };
    el.addEventListener("change", apply);
    if (el.tagName === "INPUT")
      el.addEventListener("keydown", (e) => { if (e.key === "Enter") apply(); });
  });
}

export default async function render(root, { archive = false } = {}) {
  await load(root, archive);
}
