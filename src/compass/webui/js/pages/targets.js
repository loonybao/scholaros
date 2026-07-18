/* Target Labs / Watchlist. University cards no longer dump every institution
   vacancy: roles relevant to the user show inline, and the long tail collapses
   behind a "show all institution vacancies" disclosure. Each role links to its
   detail workspace; preparation items are localised from structured data. */

import { fmtDate } from "../format.js";
import { t } from "../i18n.js";
import {
  likelihoodLabel, likelihoodTone, prepCat, prepText, valueLabel, valueTone,
} from "../labels.js";
import { badge, emptyState, esc, fetchJSON, pageHeader, panel } from "../ui.js";

const isRelevant = (o) =>
  ["exact-fit", "adjacent-methodological-fit"].includes(o.fit_type) ||
  ["apply", "consider"].includes(o.recommendation);

const oppItem = (o) =>
  `<li><a href="#/opportunities/${encodeURIComponent(o.id)}">${esc(o.title)}</a> <span class="muted">${esc(o.deadline ? fmtDate(o.deadline) : "")}</span></li>`;

function card(tg) {
  const li = (arr, render, none) => arr.length ? arr.map(render).join("") : `<li class="empty-hint">${none}</li>`;
  const people = li(tg.people, (p) => `<li>${esc(p.name)} <span class="muted">${esc(p.title || "")}</span></li>`, t("targets.none_people"));

  const relevant = tg.opportunities.filter(isRelevant);
  const other = tg.opportunities.filter((o) => !isRelevant(o));
  const relevantHtml = relevant.length
    ? `<ul>${relevant.slice(0, 8).map(oppItem).join("")}</ul>`
    : `<span class="empty-hint">${t("targets.none_opp")}</span>`;
  const otherHtml = other.length
    ? `<details class="inst-vacancies"><summary>${t("targets.show_all_inst", { n: other.length })}</summary><ul>${other.map(oppItem).join("")}</ul></details>`
    : "";

  const sigs = li(tg.latest_signals || [], (s) => `<li><a href="#/signals">${esc(s.title)}</a> ${s.recruitment_likelihood ? badge(likelihoodLabel(s.recruitment_likelihood), likelihoodTone(s.recruitment_likelihood)) : ""}</li>`, t("targets.none_signal"));
  const actions = li(tg.actions || [], (a) => `<li>${esc(a.title)} <span class="muted">${a.due_date ? esc(fmtDate(a.due_date)) : ""}</span></li>`, t("targets.none_action"));
  const prep = (tg.preparation_items || []).length
    ? `<ul>${tg.preparation_items.map((i) => `<li>${badge(prepCat(i), "neutral")} ${esc(prepText(i))}</li>`).join("")}</ul>`
    : `<span class="empty-hint">${t("targets.none_prep")}</span>`;
  const skills = (tg.recurring_skills || []).length
    ? `<div class="pill-row">${tg.recurring_skills.map(([s, n]) => `<a href="#/opportunities?skill=${encodeURIComponent(s)}">${badge(`${s} ×${n}`, "neutral")}</a>`).join("")}</div>`
    : `<span class="empty-hint">${t("common.none")}</span>`;
  return `<div class="detail-card">
    <h3>${esc(tg.name)}
      ${tg.future_group_value ? badge(`${t("dash.labs.future_value")}: ${valueLabel(tg.future_group_value)}`, valueTone(tg.future_group_value)) : ""}
      ${tg.recruitment_likelihood ? badge(`${t("dash.labs.recruitment")}: ${likelihoodLabel(tg.recruitment_likelihood)}`, likelihoodTone(tg.recruitment_likelihood)) : ""}</h3>
    <div class="muted">${esc(tg.research_direction || "")} · ${t("targets.last_checked")}: ${esc((tg.last_checked || t("targets.never")).slice(0, 10))}</div>
    <div class="detail-grid">
      <div><h4>${t("targets.people")}</h4><ul>${people}</ul></div>
      <div><h4>${t("targets.relevant_roles")} (${relevant.length})</h4>${relevantHtml}${otherHtml}</div>
      <div><h4>${t("targets.signals")}</h4><ul>${sigs}</ul></div>
      <div><h4>${t("targets.actions")}</h4><ul>${actions}</ul></div>
    </div>
    <div style="margin-top:10px"><h4>${t("targets.recurring")}</h4>${skills}</div>
    <div style="margin-top:10px"><h4>${t("targets.prepare")}</h4>${prep}</div>
  </div>`;
}

export default async function render(root) {
  const data = await fetchJSON("/api/targets");
  root.innerHTML = pageHeader(t("targets.title"), t("targets.subtitle")) +
    (data.targets.length ? data.targets.map(card).join("") : panel("", emptyState(t("targets.none"))));
}
