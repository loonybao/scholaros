/* Dashboard page — ported from the S2 implementation unchanged in
   behaviour: action required, manual tasks, analysis queue, open table,
   deadlines, review queue, health. */

import {
  badge, emptyState, esc, fetchJSON, fitText, gateBadge, panel,
  recommendationBadge, urgencyBadge,
} from "../ui.js";

function nextAction(row) {
  if (row.needs_review) return "Resolve manual review (see queue below)";
  if (row.urgency === "urgent" || row.urgency === "high")
    return "Verify posting and start application preparation";
  return "Monitor";
}

function actionCards(rows) {
  if (!rows.length)
    return emptyState("Nothing needs action right now.",
      "Apply/consider proposals and stale analyses will appear here.");
  return `<div class="cards">` + rows.map((r) => `
    <div class="card">
      <div class="card-title">${esc(r.title)}</div>
      <div class="card-org">${esc(r.org_name || r.org_id)} · ${esc(r.location || "location unknown")}</div>
      <div class="card-row">
        ${urgencyBadge(r.urgency, r.days_to_deadline)}
        ${gateBadge(r.eligibility_gate)}
        ${r.needs_review ? badge("needs review", "review") : ""}
        ${r.analysis_stale ? badge("analysis stale — renew", "uncertain") : ""}
      </div>
      <div class="card-row">Deadline: ${esc(r.deadline || "unknown")} · ${esc(fitText(r))}</div>
      ${r.recommendation ? `<div class="card-row">${recommendationBadge(r)}</div>` : ""}
      <div class="card-action">
        <span class="card-action-label">Next action</span>${esc(nextAction(r))}
      </div>
    </div>`).join("") + `</div>`;
}

function manualTasks(tasks) {
  if (!tasks.length) return "";
  return tasks.map((t) => `
    <div class="review-item">
      ${badge(t.priority, t.priority === "high" ? "urgent" : "none")}
      <strong>${esc(t.title)}</strong>
      ${t.due_date ? `<span class="card-org"> · due ${esc(t.due_date)}</span>` : ""}
    </div>`).join("") + "<br>";
}

function analysisQueue(rows) {
  if (!rows.length) return emptyState("Everything discovered has been analysed.");
  const shown = rows.slice(0, 12);
  return shown.map((r) => `
    <div class="review-item">
      ${esc(r.deadline || "no deadline")} · ${esc(r.title)}
      <span class="card-org">(${esc(r.org_name || r.org_id)})</span>
    </div>`).join("") +
    (rows.length > shown.length
      ? `<div class="empty">…and ${rows.length - shown.length} more awaiting analysis</div>`
      : "");
}

function openTable(rows) {
  if (!rows.length)
    return emptyState("No open opportunities.",
      "Run collectors or add one with: python -m compass new opportunity");
  const body = rows.map((r) => `
    <tr>
      <td><a href="${esc(r.canonical_url)}" target="_blank" rel="noopener">${esc(r.title)}</a></td>
      <td>${esc(r.org_name || r.org_id)}</td>
      <td class="num">${esc(r.deadline || "—")}</td>
      <td class="num">${r.days_to_deadline ?? "—"}</td>
      <td>${gateBadge(r.eligibility_gate)}</td>
      <td class="num">${r.fit_overall ?? "—"}</td>
      <td>${recommendationBadge(r) || "—"}</td>
      <td>${esc(r.status)}</td>
    </tr>`).join("");
  return `<div class="table-wrap"><table>
    <tr><th>Opportunity</th><th>Organisation</th><th>Deadline</th><th>Days</th>
    <th>Eligibility</th><th>Research fit</th><th>Proposal</th><th>Status</th></tr>
    ${body}</table></div>`;
}

function deadlines(rows) {
  if (!rows.length)
    return `<ul class="plain-list"><li>${emptyState("No deadlines within 45 days.")}</li></ul>`;
  return `<ul class="plain-list">` + rows.map((r) => `
    <li><span>${esc(r.title)}</span>
    <span>${esc(r.deadline)} ${urgencyBadge(r.urgency, r.days_to_deadline)}</span></li>`)
    .join("") + `</ul>`;
}

function reviewQueue(rows) {
  if (!rows.length)
    return emptyState("Queue is empty.",
      "Records with unresolved eligibility or low confidence land here.");
  return rows.slice(0, 15).map((r) => `
    <div class="review-item">
      <strong>${esc(r.title)}</strong> ${gateBadge(r.eligibility_gate)}
      <ul class="review-reasons">
        ${r.eligibility_reasons.map((x) => `<li>${esc(x)}</li>`).join("")}
      </ul>
    </div>`).join("") +
    (rows.length > 15 ? `<div class="empty">…and ${rows.length - 15} more</div>` : "");
}

function healthRow(health) {
  const counts = health.entity_counts || {};
  const items = [
    ["Opportunities", counts.opportunity ?? 0],
    ["Organisations", counts.organisation ?? 0],
    ["People", counts.person ?? 0],
    ["Signals", counts.signal ?? 0],
    ["Applications", counts.application ?? 0],
  ].map(([k, v]) =>
    `<div class="health-item"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div></div>`
  ).join("");
  const names = Object.keys(health.collectors || {});
  const collectors = names.length
    ? names.map((name) => {
        const c = health.collectors[name];
        const ok = (c.consecutive_errors || 0) === 0 && c.last_success;
        return `<div class="health-item"><div class="k">${esc(name)}</div>
          <div class="v">${badge(ok ? `ok · ${c.last_success}` : `errors: ${c.consecutive_errors || "never ran"}`, ok ? "pass" : "fail")}</div></div>`;
      }).join("")
    : `<div class="health-item"><div class="k">Collectors</div>
       <div class="v">${badge("none yet", "none")}</div></div>`;
  const llm = `<div class="health-item"><div class="k">LLM analysis</div>
    <div class="v">${badge(health.llm_configured ? "configured" : "interactive workflow", "none")}</div></div>`;
  return `<div class="health-row">${items}${collectors}${llm}</div>
    <footer class="page-footer">Index rebuilt: ${esc(health.index_rebuilt_at || "never")} ·
    Read-only intelligence UI — decisions and applications are edited via CLI.</footer>`;
}

export default async function render(root) {
  const [dash, health] = await Promise.all([
    fetchJSON("/api/dashboard"), fetchJSON("/api/health"),
  ]);
  root.innerHTML = `
    <header class="page-header">
      <h1>Research Compass — Dashboard</h1>
      <div class="header-meta">Generated ${esc(dash.generated_at)} · canonical → SQLite index → this page</div>
    </header>
    ${panel("Action required", manualTasks(dash.manual_tasks || []) + actionCards(dash.action_required))}
    ${panel("Analysis queue (not yet analysed)", analysisQueue(dash.analysis_queue || []))}
    <div class="two-col">
      ${panel("Open opportunities", openTable(dash.open_opportunities))}
      <div class="col-stack">
        ${panel("Upcoming deadlines (45 days)", deadlines(dash.upcoming_deadlines))}
        ${panel("Manual review queue", reviewQueue(dash.review_queue))}
      </div>
    </div>
    ${panel("System & collector health", healthRow(health))}
  `;
}
