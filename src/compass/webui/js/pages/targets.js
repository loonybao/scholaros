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

  const latest = (t.latest_signals || []).length
    ? t.latest_signals.map((s) => `<li><a href="#/signals">${esc(s.title)}</a>
        ${s.recruitment_likelihood ? badge(`likelihood: ${s.recruitment_likelihood}`,
          s.recruitment_likelihood === "high" ? "pass" : "uncertain") : ""}</li>`).join("")
    : "<li class='empty-hint'>none verified yet</li>";
  const prep = (t.preparation_items || []).length
    ? `<ul>${t.preparation_items.map((i) =>
        `<li>${badge(i.kind, "none")} ${esc(i.text)}</li>`).join("")}</ul>`
    : "<span class='empty-hint'>no preparation items (low-value or no analysed data)</span>";
  return `<div class="target-card">
    <h3>${esc(t.name)}
      ${t.future_group_value ? badge(`future value: ${t.future_group_value}`,
        t.future_group_value === "high" ? "pass" : "none") : ""}
      ${t.recruitment_likelihood ? badge(`recruitment likelihood: ${t.recruitment_likelihood}`,
        t.recruitment_likelihood === "high" ? "pass" : "uncertain") : ""}
      ${t.priority ? badge(`priority: ${t.priority}`, "none") : ""}
    </h3>
    <div class="card-org">${esc(t.research_direction || "no research-direction notes recorded")}
      · last checked: ${esc((t.last_checked || "never").slice(0, 10))}</div>
    <div class="target-grid">
      <div><h4>People</h4><ul>${people}</ul></div>
      <div><h4>Current & historical opportunities (${t.opportunities.length})</h4><ul>${opps}</ul></div>
      <div><h4>Latest verified signals</h4><ul>${latest}</ul></div>
      <div><h4>Open actions</h4><ul>${actions}</ul></div>
    </div>
    <div style="margin-top:10px"><h4 style="font-size:10px;text-transform:uppercase;color:var(--muted)">Recurring required skills</h4>${skills}</div>
    <div style="margin-top:10px"><h4 style="font-size:10px;text-transform:uppercase;color:var(--muted)">Prepare before vacancy</h4>${prep}</div>
  </div>`;
}

export default async function render(root) {
  const data = await fetchJSON("/api/targets");
  root.innerHTML = `
    <header class="page-header">
      <h1>Target Map / Watchlist</h1>
      <div class="header-meta">Monitored organisations and research groups, ranked by future group value — with recruitment likelihood, verified signals and prepare-before-vacancy items.</div>
    </header>
    ${panel("Targets", data.targets.length
      ? data.targets.map(targetCard).join("")
      : emptyState("No target organisations marked yet.",
          "Set manual.target=true on an organisation record."))}
  `;
}
