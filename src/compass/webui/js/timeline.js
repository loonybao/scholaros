/* Visual graduation timeline. The road from now to expected MSc completion,
   divided into the four phases (monitor & build -> prepare -> outreach ->
   active), with the current phase highlighted and a "you are here" marker.
   Purely a view over the graduation_horizon payload. */

"use strict";

import { fmtMonthYear } from "./format.js";
import { t } from "./i18n.js";
import { phaseLabel } from "./labels.js";
import { esc } from "./ui.js";

const ms = (iso) => new Date(iso.length <= 10 ? `${iso}T00:00:00` : iso).getTime();

// Each phase spans from one milestone to the next; map to the phase enum.
const PHASES = [
  ["milestone.now", "milestone.prepare", "monitor_and_build"],
  ["milestone.prepare", "milestone.outreach", "prepare"],
  ["milestone.outreach", "milestone.active", "outreach_window"],
  ["milestone.active", "milestone.graduation", "active_application"],
];

export function graduationTimeline(h, { compact = false } = {}) {
  if (!h || !h.milestones || !h.milestones.length) return "";
  const byKey = Object.fromEntries(h.milestones.map((m) => [m.key, m.date]));
  const start = ms(byKey["milestone.now"]);
  const end = ms(h.expected_graduation);
  const span = Math.max(1, end - start);
  const pct = (iso) => Math.max(0, Math.min(100, ((ms(iso) - start) / span) * 100));

  const bands = PHASES.map(([fromKey, toKey, phase], i) => {
    const left = pct(byKey[fromKey]);
    const right = pct(byKey[toKey]);
    const width = Math.max(0, right - left);
    if (width <= 0) return "";
    const current = h.current_phase === phase ? "current" : "";
    return `<div class="gtl-band gtl-p${i} ${current}" style="left:${left}%;width:${width}%">
      <span class="gtl-band-label">${esc(phaseLabel(phase))}</span></div>`;
  }).join("");

  const months = Math.round(h.months_to_graduation);
  const certainty = t(`label.certainty.${h.certainty || "estimated"}`);
  const head = `<div class="gtl-head">
      <span class="gtl-phase-now">${esc(phaseLabel(h.current_phase))}</span>
      <span class="gtl-months">${t("dash.hero.months_short", { n: months })}</span>
    </div>`;

  return `<div class="gtl ${compact ? "compact" : ""}">
    ${head}
    <div class="gtl-track">
      ${bands}
      <div class="gtl-now" style="left:0%"><span>${t("roadmap.you_are_here")}</span></div>
    </div>
    <div class="gtl-axis">
      <span>${t("roadmap.now")}</span>
      <span>${esc(fmtMonthYear(h.expected_graduation))} · ${esc(certainty)}</span>
    </div>
  </div>`;
}
