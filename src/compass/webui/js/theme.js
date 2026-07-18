/* Theme system: System / Light / Dark. The colour values live in CSS custom
   properties keyed off <html data-theme>; this module only toggles the
   attribute and persists the choice. System follows prefers-color-scheme
   (handled in CSS), so no JS re-render is needed on OS changes. */

"use strict";

export const THEMES = ["system", "light", "dark"];

export function initTheme() {
  const stored = localStorage.getItem("theme");
  apply(THEMES.includes(stored) ? stored : "system");
}

export function setTheme(theme) {
  apply(THEMES.includes(theme) ? theme : "system");
  document.dispatchEvent(new CustomEvent("theme-changed"));
}

export function getTheme() {
  return document.documentElement.getAttribute("data-theme") || "system";
}

function apply(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem("theme", theme);
}
