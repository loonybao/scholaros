/* Raw internal enum values are NEVER shown to the user. Every enum maps to a
   translated label and a semantic colour tone here. */

"use strict";

import { t } from "./i18n.js";

export const timingLabel = (v) => (v ? t(`label.timing.${v}`) : "");
export const fitLabel = (v) => (v ? t(`label.fit.${v}`) : "");
export const recLabel = (v) => (v ? t(`label.rec.${v}`) : "");
export const gateLabel = (v) => (v ? t(`label.gate.${v}`) : "");
export const likelihoodLabel = (v) => (v ? t(`label.likelihood.${v}`) : "");
export const valueLabel = (v) => (v ? t(`label.value.${v}`) : "");
export const skillStatusLabel = (v) => (v ? t(`label.skill.${v}`) : "");
export const contactLabel = (v) => (v ? t(`label.contact.${v}`) : "");
export const reasonLabel = (v) => (v ? t(`label.reason.${v}`) : "");
export const stageLabel = (v) => (v ? t(`app.stage.${v}`) : "");
export const phaseLabel = (v) => (v ? t(`phase.${v}`) : "");
export const statusLabel = (v) => (v ? t(`label.status.${v}`) : "");

// Structured preparation items are localised here (no baked-in English is ever
// stored server-side). See index.preparation_items for the item shapes.
export function prepText(i) {
  switch (i.kind) {
    case "strengthen": return t("prep.strengthen", { skill: i.skill, count: i.count });
    case "learn": return t("prep.learn", { skill: i.skill, count: i.count });
    case "portfolio": return t("prep.portfolio", { skill: i.skill, count: i.count });
    case "monitor_person": return t("prep.monitor_person", { person: i.person });
    case "monitor_signal": return t("prep.monitor_signal");
    default: return "";
  }
}
export function prepCat(i) {
  if (i.kind === "monitor_person" || i.kind === "monitor_signal") return t("prep.cat.monitor");
  if (i.kind === "portfolio") return t("prep.cat.portfolio");
  return t("prep.cat.skill");
}

// Colour semantics: good(green)=actionable/done, info(blue)=future/info,
// warn(amber)=needs confirmation, danger(red)=urgent/failure, neutral(grey)=
// historical/rejected/non-current. Deliberately not everything amber.
export const timingTone = (v) => ({
  actionable_now: "good", prepare_for_current_cycle: "info",
  future_target: "info", timing_mismatch: "neutral", timing_unknown: "warn",
}[v] || "neutral");
export const recTone = (v) => ({
  apply: "good", consider: "info", monitor: "neutral", reject: "neutral",
}[v] || "neutral");
export const gateTone = (v) => ({ pass: "good", uncertain: "warn", fail: "neutral" }[v] || "neutral");
export const likelihoodTone = (v) => ({ high: "good", moderate: "warn", low: "neutral" }[v] || "neutral");
export const valueTone = (v) => ({ high: "good", medium: "info", low: "neutral" }[v] || "neutral");
export const skillTone = (v) => ({
  strength: "good", maintain: "info", learn_next: "warn",
  optional: "neutral", not_relevant: "neutral",
}[v] || "neutral");
