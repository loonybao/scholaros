/* Roadmap — the full graduation-horizon plan (from the dashboard payload). */

import { fmtDate, fmtMonthYear } from "../format.js";
import { t } from "../i18n.js";
import { phaseLabel } from "../labels.js";
import { graduationTimeline } from "../timeline.js";
import { badge, emptyState, esc, fetchJSON, pageHeader, panel } from "../ui.js";

export default async function render(root) {
  const dash = await fetchJSON("/api/dashboard");
  const h = dash.graduation_horizon;
  if (!h) { root.innerHTML = pageHeader(t("roadmap.title"), t("roadmap.subtitle")) + panel("", emptyState(t("roadmap.none"))); return; }

  const win = (labelKey, w) => `<div><h4>${t(labelKey)}</h4><div class="v">${esc(fmtMonthYear(w.from))} – ${esc(fmtMonthYear(w.to))}</div></div>`;
  // Milestones are structured {date, key, certainty?}; localise via t(key).
  const milestoneText = (m) => t(m.key, m.certainty ? { certainty: t(`label.certainty.${m.certainty}`) } : undefined);
  const milestones = h.milestones.map((m) =>
    `<li><span>${esc(milestoneText(m))}</span><span class="m-date">${esc(fmtDate(m.date))}</span></li>`).join("");

  root.innerHTML = pageHeader(t("roadmap.title"), t("roadmap.subtitle")) +
    panel(t("roadmap.timeline"), graduationTimeline(h)) +
    panel("", `<div class="card-row" style="margin-bottom:10px">
        ${badge(`${t("roadmap.phase")}: ${phaseLabel(h.current_phase)}`, "info")}
        ${badge(t("roadmap.months", { n: Math.round(h.months_to_graduation) }), "neutral")}
        ${badge(`${t("roadmap.expected")}: ${fmtMonthYear(h.expected_graduation)}`, "neutral")}
      </div>
      <p class="muted">${t(`phase.guidance.${h.current_phase}`)}</p>
      <div class="window-grid">
        ${win("roadmap.prep_window", h.preparation_window)}
        ${win("roadmap.outreach_window", h.outreach_window)}
        ${win("roadmap.active_window", h.active_application_window)}
      </div>`) +
    panel(t("roadmap.milestones"), `<ul class="milestones">${milestones}</ul>`);
}
