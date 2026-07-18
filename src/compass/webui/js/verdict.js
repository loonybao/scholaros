/* The "bottom line": one plain-language sentence synthesising the deterministic
   signals (eligibility gate, timing, effective recommendation) into what the
   user should actually do. Deterministic — a view over derived data, no new
   judgement. Localised via t(). */

"use strict";

import { t } from "./i18n.js";

const ACTIONABLE = ["actionable_now", "prepare_for_current_cycle"];

/** Returns {key, tone} for a detail payload's derived+ai layers. */
export function bottomLine(d) {
  const der = d.derived || {};
  const gate = der.eligibility_gate;
  const timing = der.timing_assessment;
  const rec = der.effective_recommendation;

  if (gate === "fail") return { key: "verdict.not_eligible", tone: "neutral" };
  if (timing === "timing_mismatch") return { key: "verdict.timing_early", tone: "info" };
  if (timing === "future_target") return { key: "verdict.future_target", tone: "info" };
  if (rec === "apply" && (timing == null || ACTIONABLE.includes(timing)))
    return { key: "verdict.apply", tone: "good" };
  if (rec === "consider") return { key: "verdict.consider", tone: "info" };
  if (gate === "uncertain") return { key: "verdict.uncertain", tone: "warn" };
  return { key: "verdict.monitor", tone: "neutral" };
}

export function bottomLineHtml(d) {
  const { key, tone } = bottomLine(d);
  return `<div class="bottom-line tone-${tone}"><span class="bl-icon" aria-hidden="true">➤</span>${t(key)}</div>`;
}
