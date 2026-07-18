/* Application Pipeline — kanban by stage; data inherited from the vacancy. */

import { fmtDate } from "../format.js";
import { t } from "../i18n.js";
import { stageLabel } from "../labels.js";
import { emptyState, esc, fetchJSON, pageHeader, panel, sourceLink } from "../ui.js";

const STAGES = ["identified", "preparing", "submitted", "monitoring",
  "awaiting_response", "interview", "offered", "rejected", "withdrawn"];

function card(a) {
  const blockers = a.blockers.length ? `<ul>${a.blockers.map((b) => `<li>${esc(b)}</li>`).join("")}</ul>` : "";
  return `<div class="kanban-card">
    <div class="k-title">${esc(a.opportunity_title)}</div>
    <div>${a.official_deadline ? `${t("app.deadline")}: <strong>${esc(fmtDate(a.official_deadline))}</strong>` : t("common.none")}
      ${a.internal_due_date ? ` · ${t("app.internal")}: ${esc(fmtDate(a.internal_due_date))}` : ""}</div>
    ${a.next_step ? `<div>${t("app.next")}: ${esc(a.next_step)}${a.next_step_due ? ` (${esc(fmtDate(a.next_step_due))})` : ""}</div>` : ""}
    ${blockers}
    ${a.official_url ? `<div>${sourceLink(a.official_url, "app.official_page")}</div>` : ""}
  </div>`;
}

export default async function render(root) {
  const data = await fetchJSON("/api/applications");
  const cols = STAGES.filter((s) => (data.stages[s] || []).length ||
      ["identified", "preparing", "submitted"].includes(s))
    .map((s) => `<div class="kanban-col"><h3>${stageLabel(s)} (${(data.stages[s] || []).length})</h3>
      ${(data.stages[s] || []).map(card).join("") || `<div class="empty">${t("common.none")}</div>`}</div>`).join("");
  root.innerHTML = pageHeader(t("app.title"), t("app.subtitle", { n: data.total })) +
    (data.total ? `<section class="panel"><div class="kanban">${cols}</div></section>`
      : panel("", emptyState(t("app.none"))));
}
