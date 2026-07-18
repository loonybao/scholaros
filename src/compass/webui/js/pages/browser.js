/* Opportunity Browser + Archive/Audit.
   - Opportunities (default): a card view scoped to roles relevant to you, each
     card opening the detail workspace. This is the working surface.
   - Archive: the full server-filtered audit table — rejected and poor-fit
     records included. Nothing is ever hidden from the audit.
   Both are read-only here; edits happen in the opportunity detail workspace. */

import { fmtDate } from "../format.js";
import { t } from "../i18n.js";
import {
  fitLabel, gateLabel, gateTone, reasonLabel, recLabel, recTone,
  timingLabel, timingTone, valueLabel, valueTone,
} from "../labels.js";
import { badge, emptyState, esc, fetchJSON, pageHeader, panel } from "../ui.js";

const statusLabel = (v) => (v ? t(`label.status.${v}`) : "");

const ENUM_FILTERS = {
  fit_type: ["exact-fit", "adjacent-methodological-fit", "poor-fit"],
  recommendation: ["apply", "consider", "monitor", "reject"],
  eligibility_gate: ["pass", "uncertain", "fail"],
  rejection_reason: ["poor_research_fit", "eligibility_mismatch", "degree_timing_mismatch",
    "career_stage_mismatch", "unpaid_or_self_funded", "language_requirement",
    "mobility_or_location_constraint", "deadline_passed", "user_not_interested"],
  future_group_value: ["high", "medium", "low"],
  timing_assessment: ["actionable_now", "prepare_for_current_cycle", "future_target",
    "timing_mismatch", "timing_unknown"],
  position_type: ["phd", "postdoc", "project_researcher", "research_assistant", "other"],
  deadline_status: ["upcoming", "past", "none"],
  status: ["open", "closed", "expired", "unknown"],
};
// Friendly option labels per filter value.
const OPT_LABEL = {
  fit_type: fitLabel, recommendation: recLabel, eligibility_gate: gateLabel,
  rejection_reason: reasonLabel, future_group_value: valueLabel,
  timing_assessment: timingLabel,
  position_type: (v) => v, status: (v) => v,
  deadline_status: (v) => t(`opp.deadline.${v}`),
};

function qs() { return Object.fromEntries(new URLSearchParams(window.location.hash.split("?")[1] || "").entries()); }

// Relevant-scope working view: one card per role, opening the detail workspace.
function cards(rows) {
  if (!rows.length) return emptyState(t("opp.none"), t("opp.none_hint"));
  const body = rows.map((r) => {
    const org = (r.org_name || r.org_id || "").replace(/ \(.*\)$/, "");
    return `<a class="opp-card" href="#/opportunities/${encodeURIComponent(r.id)}">
      <div class="opp-card-head">
        <h3>${esc(r.title)}</h3>
        ${r.user_status ? badge(statusLabel(r.user_status), "info") : ""}
      </div>
      <div class="opp-card-org">${esc(org)}${r.position_type ? ` · ${esc(r.position_type)}` : ""}</div>
      <div class="opp-card-badges">
        ${badge(gateLabel(r.eligibility_gate), gateTone(r.eligibility_gate))}
        ${r.recommendation ? badge(recLabel(r.recommendation), recTone(r.recommendation)) : ""}
        ${r.timing_assessment ? badge(timingLabel(r.timing_assessment), timingTone(r.timing_assessment)) : ""}
        ${r.fit_overall != null ? badge(`${t("opp.col.fit")}: ${r.fit_overall}`, "info") : ""}
      </div>
      <div class="opp-card-foot">
        <span>${esc(r.deadline ? fmtDate(r.deadline) : t("common.none"))} <span class="muted">(${t("opp.deadline." + r.deadline_status)})</span></span>
        <span class="opp-card-open">${t("opp.open_detail")} →</span>
      </div>
    </a>`;
  }).join("");
  return `<div class="opp-cards">${body}</div>`;
}

function table(rows) {
  if (!rows.length) return emptyState(t("opp.none"), t("opp.none_hint"));
  const body = rows.map((r) => `
    <tr>
      <td><a href="${esc(r.canonical_url)}" target="_blank" rel="noopener">${esc(r.title)}</a></td>
      <td>${esc((r.org_name || r.org_id || "").replace(/ \(.*\)$/, ""))}</td>
      <td>${esc(r.position_type)}</td>
      <td class="num">${esc(r.deadline ? fmtDate(r.deadline) : t("common.none"))} <span class="muted">(${t("opp.deadline." + r.deadline_status)})</span></td>
      <td>${badge(gateLabel(r.eligibility_gate), gateTone(r.eligibility_gate))}</td>
      <td class="num">${r.fit_overall ?? t("common.none")}</td>
      <td>${r.recommendation ? badge(recLabel(r.recommendation), recTone(r.recommendation)) : t("common.none")}</td>
      <td>${r.timing_assessment ? badge(timingLabel(r.timing_assessment), timingTone(r.timing_assessment)) : t("common.none")}</td>
      <td>${r.rejection_reasons.map((x) => badge(reasonLabel(x), "neutral")).join(" ") || t("common.none")}</td>
      <td>${r.future_group_value ? badge(valueLabel(r.future_group_value), valueTone(r.future_group_value)) : t("common.none")}</td>
    </tr>`).join("");
  return `<div class="table-wrap"><table>
    <tr><th>${t("opp.col.opportunity")}</th><th>${t("opp.col.organisation")}</th><th>${t("opp.col.stage")}</th>
    <th>${t("opp.col.deadline")}</th><th>${t("opp.col.gate")}</th><th>${t("opp.col.fit")}</th>
    <th>${t("opp.col.proposal")}</th><th>${t("opp.col.timing")}</th><th>${t("opp.col.reasons")}</th>
    <th>${t("opp.col.value")}</th></tr>${body}</table></div>`;
}

async function load(root, archive) {
  const active = qs();
  // The default Opportunities page is scoped to relevant roles; Archive is the
  // full audit. Scope is applied at fetch time and kept out of the filter chips.
  const params = new URLSearchParams(active);
  if (!archive) params.set("scope", "relevant");
  const data = await fetchJSON("/api/opportunities" + (params.toString() ? `?${params}` : ""));
  const rows = data.opportunities;
  const orgs = [...new Map(rows.map((r) => [r.org_id, r.org_name || r.org_id])).entries()];
  const labs = [...new Map(rows.filter((r) => r.lab_org_id).map((r) => [r.lab_org_id, r.lab_name || r.lab_org_id])).entries()];
  const skills = [...new Set(rows.flatMap((r) => r.required_skills.concat(r.preferred_skills)))].sort();

  root.innerHTML = pageHeader(
    archive ? t("opp.archive_title") : t("opp.title"),
    archive ? t("opp.archive_subtitle") : t("opp.subtitle")) +
    (archive ? "" : `<div class="scope-hint">${t("opp.scope.hint")} <a href="#/archive">${t("opp.view_archive")} →</a></div>`) +
    panel(t("opp.filter.q"), filterBarSafe(active, orgs, labs, skills)) +
    panel("", archive ? table(rows) : cards(rows));
  root.querySelector("#cnt").textContent = t("opp.count", { n: data.count });

  root.querySelectorAll("[data-filter]").forEach((el) => {
    const apply = () => {
      const p = new URLSearchParams(window.location.hash.split("?")[1] || "");
      if (el.value) p.set(el.dataset.filter, el.value); else p.delete(el.dataset.filter);
      window.location.hash = `${archive ? "#/archive" : "#/opportunities"}?${p}`;
    };
    el.addEventListener("change", apply);
    if (el.tagName === "INPUT") el.addEventListener("keydown", (e) => { if (e.key === "Enter") apply(); });
  });
}

// Build the filter bar with explicit institution/lab labels.
function filterBarSafe(active, orgs, labs, skills) {
  const sel = (name, labelText, options) => {
    const opts = [`<option value="">${t("opp.filter.any")}</option>`]
      .concat(options.map(([v, label]) => `<option value="${esc(v)}" ${active[name] === v ? "selected" : ""}>${esc(label)}</option>`));
    return `<label>${esc(labelText)} <select data-filter="${name}">${opts.join("")}</select></label>`;
  };
  const parts = [
    sel("org_id", t("opp.filter.institution"), orgs.map(([v, l]) => [v, String(l).replace(/ \(.*\)$/, "")])),
    sel("lab_org_id", t("opp.filter.lab"), labs.map(([v, l]) => [v, String(l).replace(/ \(.*\)$/, "")])),
  ];
  for (const [name, values] of Object.entries(ENUM_FILTERS))
    parts.push(sel(name, t("opp.filter." + name), values.map((v) => [v, OPT_LABEL[name](v)])));
  parts.push(sel("skill", t("opp.filter.skill"), skills.map((s) => [s, s])));
  parts.push(`<label>${t("opp.filter.q")} <input type="text" data-filter="q" value="${esc(active.q || "")}" placeholder="${t("opp.filter.q_placeholder")}"></label>`);
  parts.push(`<span class="result-count" id="cnt"></span>`);
  return `<div class="filter-bar">${parts.join("")}</div>`;
}

export default async function render(root, { archive = false } = {}) {
  await load(root, archive);
}
