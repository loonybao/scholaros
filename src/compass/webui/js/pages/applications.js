/* Application Pipeline — kanban by stage, data inherited from the linked
   vacancy records. Read-only; edits go through the CLI. */

import { badge, emptyState, esc, fetchJSON, panel } from "../ui.js";

const STAGE_ORDER = [
  "identified", "preparing", "submitted", "monitoring", "awaiting_response",
  "interview", "offered", "rejected", "withdrawn",
];

function card(a) {
  const blockers = a.blockers.length
    ? `<ul>${a.blockers.map((b) => `<li>${esc(b)}</li>`).join("")}</ul>` : "";
  return `<div class="kanban-card">
    <div class="k-title">${esc(a.opportunity_title)}</div>
    <div>${a.official_deadline
      ? `Official deadline: <strong>${esc(a.official_deadline)}</strong>` : "No official deadline"}
      ${a.internal_due_date ? ` · internal: ${esc(a.internal_due_date)}` : ""}</div>
    ${a.next_step ? `<div>Next: ${esc(a.next_step)}${a.next_step_due ? ` (due ${esc(a.next_step_due)})` : ""}</div>` : ""}
    ${blockers}
    ${a.official_url ? `<div><a href="${esc(a.official_url)}" target="_blank" rel="noopener">official page</a></div>` : ""}
  </div>`;
}

export default async function render(root) {
  const data = await fetchJSON("/api/applications");
  const columns = STAGE_ORDER
    .filter((s) => (data.stages[s] || []).length || ["identified", "preparing", "submitted"].includes(s))
    .map((s) => `<div class="kanban-col">
      <h3>${esc(s)} (${(data.stages[s] || []).length})</h3>
      ${(data.stages[s] || []).map(card).join("") ||
        `<div class="empty">—</div>`}
    </div>`).join("");
  root.innerHTML = `
    <header class="page-header">
      <h1>Application Pipeline</h1>
      <div class="header-meta">${data.total} application record(s) — deadlines and links inherited live from the vacancy records.</div>
    </header>
    ${data.total ? `<section class="panel"><div class="kanban">${columns}</div></section>`
      : panel("Pipeline", emptyState("No application records yet."))}
  `;
}
