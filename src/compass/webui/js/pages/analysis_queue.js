/* Analysis Queue (System) — operational backlog, moved off the Dashboard. */

import { fmtDate } from "../format.js";
import { t } from "../i18n.js";
import { gateLabel, gateTone } from "../labels.js";
import { badge, emptyState, esc, fetchJSON, pageHeader, panel } from "../ui.js";

export default async function render(root) {
  const dash = await fetchJSON("/api/dashboard");
  const queue = dash.analysis_queue || [];
  const review = dash.review_queue || [];

  const queueRows = queue.length
    ? queue.map((r) => `<div class="item-row">${esc(r.deadline ? fmtDate(r.deadline) : t("common.none"))} ·
        ${esc(r.title)} <span class="muted">(${esc((r.org_name || r.org_id || "").replace(/ \(.*\)$/, ""))})</span></div>`).join("")
    : emptyState(t("sys.queue.none"));

  const reviewRows = review.length
    ? review.map((r) => `<div class="item-row"><strong>${esc(r.title)}</strong> ${badge(gateLabel(r.eligibility_gate), gateTone(r.eligibility_gate))}
        <ul class="item-reasons">${r.eligibility_reasons.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>`).join("")
    : emptyState(t("sys.queue.none"));

  root.innerHTML = pageHeader(t("sys.queue.title"), t("sys.queue.subtitle")) +
    panel(t("sys.queue.unanalysed", { n: queue.length }), queueRows) +
    panel(t("sys.queue.review", { n: review.length }), reviewRows);
}
