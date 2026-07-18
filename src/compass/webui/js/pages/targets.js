/* Target Map — monitored organisations/groups with linked people, vacancies,
   signals, actions and recurring skills. Navigation into the browser is by
   institution/lab filter. */

import { badge, emptyState, esc, fetchJSON, panel } from "../ui.js";

function targetCard(t) {
  const people = t.people.length
    ? t.people.map((p) => `<li>${esc(p.name)} <span class="card-org">
        ${esc(p.title || "")} · ${esc(p.contact_status)}</span></li>`).join("")
    : "<li class='empty-hint'>none recorded</li>";
  const opps = t.opportunities.length
    ? t.opportunities.slice(0, 8).map((o) => `<li>
        <a href="#/opportunities?lab_org_id=${encodeURIComponent(t.id)}">${esc(o.title)}</a>
        <span class="card-org">${esc(o.deadline || "")} · ${esc(o.recommendation || "unanalysed")}</span></li>`).join("")
    : "<li class='empty-hint'>none linked</li>";
  const signals = t.signals.length
    ? t.signals.map((s) => `<li>${esc(s.title)} <span class="card-org">(${esc(s.signal_type)})</span></li>`).join("")
    : "<li class='empty-hint'>none</li>";
  const actions = t.actions.length
    ? t.actions.map((a) => `<li>${esc(a.title)} <span class="card-org">
        ${a.due_date ? "due " + esc(a.due_date) : ""}</span></li>`).join("")
    : "<li class='empty-hint'>none open</li>";
  const skills = t.recurring_skills.length
    ? `<div class="pill-row">${t.recurring_skills.map(([s, n]) =>
        `<a href="#/opportunities?skill=${encodeURIComponent(s)}">${badge(`${s} ×${n}`, "none")}</a>`).join("")}</div>`
    : "<span class='empty-hint'>no analysed vacancies yet</span>";

  return `<div class="target-card">
    <h3>${esc(t.name)}
      ${t.future_group_value ? badge(`future value: ${t.future_group_value}`,
        t.future_group_value === "high" ? "pass" : "none") : ""}
      ${t.priority ? badge(`priority: ${t.priority}`, "none") : ""}
    </h3>
    <div class="card-org">${esc(t.research_direction || "no research-direction notes recorded")}</div>
    <div class="target-grid">
      <div><h4>People</h4><ul>${people}</ul></div>
      <div><h4>Linked opportunities (${t.opportunities.length})</h4><ul>${opps}</ul></div>
      <div><h4>Signals</h4><ul>${signals}</ul></div>
      <div><h4>Open actions</h4><ul>${actions}</ul></div>
    </div>
    <div style="margin-top:10px"><h4 style="font-size:10px;text-transform:uppercase;color:var(--muted)">Recurring required skills</h4>${skills}</div>
  </div>`;
}

export default async function render(root) {
  const data = await fetchJSON("/api/targets");
  root.innerHTML = `
    <header class="page-header">
      <h1>Target Map</h1>
      <div class="header-meta">Monitored organisations and research groups, ranked by future group value.</div>
    </header>
    ${panel("Targets", data.targets.length
      ? data.targets.map(targetCard).join("")
      : emptyState("No target organisations marked yet.",
          "Set manual.target=true on an organisation record."))}
  `;
}
