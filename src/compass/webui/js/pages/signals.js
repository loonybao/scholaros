/* Signal Feed — verified future-recruitment intelligence. Signals never
   enter Action Required; only their concrete Action records do. */

import { badge, emptyState, esc, fetchJSON, panel } from "../ui.js";

const LIKELIHOOD_KIND = { high: "pass", moderate: "uncertain", low: "none" };

function signalCard(s) {
  const people = s.people.length
    ? `<div><h4>People</h4><ul>${s.people.map((p) =>
        `<li>${esc(p.name)} <span class="card-org">${esc(p.title || "")}</span></li>`).join("")}</ul></div>`
    : "";
  const opps = s.opportunities.length
    ? `<div><h4>Linked opportunities</h4><ul>${s.opportunities.map((o) =>
        `<li>${esc(o.title)} <span class="card-org">${esc(o.deadline || "")} · ${esc(o.recommendation || "unanalysed")}</span></li>`).join("")}</ul></div>`
    : "";
  const risks = s.risks.length
    ? `<div><h4>Risks & uncertainties</h4><ul>${s.risks.map((r) =>
        `<li>${esc(r)}</li>`).join("")}</ul></div>`
    : "";
  return `<div class="target-card">
    <h3>${esc(s.title)}</h3>
    <div class="card-row">
      ${badge(s.signal_type, "none")}
      ${s.recruitment_likelihood
        ? badge(`recruitment likelihood: ${s.recruitment_likelihood}`,
                LIKELIHOOD_KIND[s.recruitment_likelihood])
        : badge("not triaged", "none")}
      ${s.confidence != null ? badge(`confidence ${s.confidence}`, "none") : ""}
      <span class="card-org">${esc(s.org_name || s.org_id || "")} ·
        ${esc(s.published_at || s.retrieved_at || "date unknown")}</span>
    </div>
    <div class="card-org" style="margin:6px 0">${esc(s.excerpt || "")}</div>
    ${s.recruitment_rationale
      ? `<div class="skill-detail"><strong>Rationale:</strong> ${esc(s.recruitment_rationale)}</div>` : ""}
    <div class="target-grid">${people}${opps}${risks}</div>
    ${s.url ? `<div style="margin-top:8px"><a href="${esc(s.url)}" target="_blank" rel="noopener">official source</a></div>` : ""}
  </div>`;
}

export default async function render(root) {
  const data = await fetchJSON("/api/signals");
  root.innerHTML = `
    <header class="page-header">
      <h1>Signal Feed</h1>
      <div class="header-meta">Verified future-recruitment intelligence. Generic XR activity is never a strong signal without methodological alignment.</div>
    </header>
    ${panel("Signals", data.signals.length
      ? data.signals.map(signalCard).join("")
      : emptyState("No signals recorded yet.",
          "Add one with: python -m compass new signal --from-file stub.yaml"))}
  `;
}
