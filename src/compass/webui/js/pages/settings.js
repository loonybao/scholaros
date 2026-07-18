/* Settings — appearance and language. No secrets or API config are exposed. */

import { getLocale, LOCALE_LABELS, LOCALES, setLocale, t } from "../i18n.js";
import { getTheme, setTheme, THEMES } from "../theme.js";
import { esc, pageHeader, panel } from "../ui.js";

function radioGroup(name, options, current, labelFn) {
  return `<div class="filter-bar" role="radiogroup" aria-label="${esc(name)}">
    ${options.map((v) => `<label><input type="radio" name="${name}" value="${esc(v)}" ${v === current ? "checked" : ""}> ${esc(labelFn(v))}</label>`).join("")}
  </div>`;
}

export default async function render(root) {
  root.innerHTML = pageHeader(t("settings.title"), "") +
    panel(t("settings.appearance"),
      `<p class="muted">${t("settings.appearance_help")}</p>` +
      radioGroup("theme", THEMES, getTheme(), (v) => t(`theme.${v}`))) +
    panel(t("settings.language"),
      `<p class="muted">${t("settings.language_help")}</p>` +
      radioGroup("locale", LOCALES, getLocale(), (v) => LOCALE_LABELS[v]));

  root.querySelectorAll('input[name="theme"]').forEach((el) =>
    el.addEventListener("change", () => setTheme(el.value)));
  root.querySelectorAll('input[name="locale"]').forEach((el) =>
    el.addEventListener("change", () => setLocale(el.value)));
}
