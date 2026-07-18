/* Signal Feed — verified future-recruitment intelligence. */

import { fmtDate } from "../format.js";
import { t } from "../i18n.js";
import { likelihoodLabel, likelihoodTone } from "../labels.js";
import { badge, emptyState, esc, fetchJSON, pageHeader, panel, sourceLink } from "../ui.js";

function card(s) {
  const list = (title, arr, render) => arr.length ? `<div><h4>${title}</h4><ul>${arr.map(render).join("")}</ul></div>` : "";
  const people = list(t("signals.people"), s.people, (p) => `<li>${esc(p.name)} <span class="muted">${esc(p.title || "")}</span></li>`);
  const opps = list(t("signals.opportunities"), s.opportunities, (o) => `<li>${esc(o.title)} <span class="muted">${esc(o.deadline ? fmtDate(o.deadline) : "")}</span></li>`);
  const risks = list(t("signals.risks"), s.risks, (r) => `<li>${esc(r)}</li>`);
  return `<div class="detail-card">
    <h3>${esc(s.title)}</h3>
    <div class="card-row">
      ${badge(s.signal_type, "neutral")}
      ${s.recruitment_likelihood ? badge(`${t("signals.likelihood")}: ${likelihoodLabel(s.recruitment_likelihood)}`, likelihoodTone(s.recruitment_likelihood)) : badge(t("signals.not_triaged"), "neutral")}
      ${s.confidence != null ? badge(t("signals.confidence", { n: s.confidence }), "neutral") : ""}
      <span class="muted">${esc(s.org_name || s.org_id || "")} · ${esc(s.published_at ? fmtDate(s.published_at) : (s.retrieved_at ? fmtDate(s.retrieved_at) : t("common.date_unknown")))}</span>
    </div>
    <div class="muted" style="margin:6px 0">${esc(s.excerpt || "")}</div>
    ${s.recruitment_rationale ? `<div class="skill-detail"><strong>${t("signals.rationale")}:</strong> ${esc(s.recruitment_rationale)}</div>` : ""}
    <div class="detail-grid">${people}${opps}${risks}</div>
    <div style="margin-top:8px">${sourceLink(s.url, "signals.source")}</div>
  </div>`;
}

export default async function render(root) {
  const data = await fetchJSON("/api/signals");
  root.innerHTML = pageHeader(t("signals.title"), t("signals.subtitle")) +
    (data.signals.length ? data.signals.map(card).join("") : panel("", emptyState(t("signals.none"))));
}
