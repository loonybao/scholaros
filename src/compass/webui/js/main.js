/* App shell: theme + i18n bootstrap, grouped navigation, topbar selectors,
   and the hash router. Page modules export default async render(root, opts). */

"use strict";

import { getLocale, initI18n, LOCALES, LOCALE_LABELS, setLocale, t } from "./i18n.js";
import { getTheme, initTheme, setTheme, THEMES } from "./theme.js";
import renderApplications from "./pages/applications.js";
import renderBrowser from "./pages/browser.js";
import renderDashboard from "./pages/dashboard.js";
import renderDataHealth from "./pages/data_health.js";
import renderQueue from "./pages/analysis_queue.js";
import renderResearchers from "./pages/researchers.js";
import renderReviews from "./pages/reviews.js";
import renderRoadmap from "./pages/roadmap.js";
import renderSettings from "./pages/settings.js";
import renderSignals from "./pages/signals.js";
import renderSkills from "./pages/skills.js";
import renderTargets from "./pages/targets.js";

const ROUTES = {
  dashboard: { render: (r) => renderDashboard(r), navKey: "nav.dashboard" },
  opportunities: { render: (r) => renderBrowser(r, { archive: false }), navKey: "nav.opportunities" },
  targets: { render: (r) => renderTargets(r), navKey: "nav.target_labs" },
  researchers: { render: (r) => renderResearchers(r), navKey: "nav.researchers" },
  signals: { render: (r) => renderSignals(r), navKey: "nav.signals" },
  skills: { render: (r) => renderSkills(r), navKey: "nav.skills" },
  archive: { render: (r) => renderBrowser(r, { archive: true }), navKey: "nav.archive" },
  roadmap: { render: (r) => renderRoadmap(r), navKey: "nav.roadmap" },
  applications: { render: (r) => renderApplications(r), navKey: "nav.applications" },
  reviews: { render: (r) => renderReviews(r), navKey: "nav.reviews" },
  "analysis-queue": { render: (r) => renderQueue(r), navKey: "nav.analysis_queue" },
  "data-health": { render: (r) => renderDataHealth(r), navKey: "nav.data_health" },
  settings: { render: (r) => renderSettings(r), navKey: "nav.settings" },
};

const NAV_GROUPS = [
  { label: "nav.group.today", items: [["dashboard", "◎"]] },
  { label: "nav.group.explore", items: [
    ["opportunities", "▤"], ["targets", "⌂"], ["researchers", "◍"],
    ["signals", "◈"], ["skills", "▚"], ["archive", "▦"],
  ] },
  { label: "nav.group.plan", items: [
    ["roadmap", "→"], ["applications", "✎"], ["reviews", "↻"],
  ] },
  { label: "nav.group.system", items: [
    ["analysis-queue", "≡"], ["data-health", "♥"], ["settings", "⚙"],
  ] },
];

function currentRoute() {
  const path = window.location.hash.replace(/^#\/?/, "").split("?")[0];
  return ROUTES[path] ? path : "dashboard";
}

function renderNav() {
  const active = currentRoute();
  document.getElementById("nav").innerHTML = NAV_GROUPS.map((g) => `
    <div class="nav-group-label">${t(g.label)}</div>
    ${g.items.map(([route, ico]) => `
      <a class="nav-item ${route === active ? "active" : ""}"
         href="#/${route}" ${route === active ? 'aria-current="page"' : ""}>
        <span class="nav-ico" aria-hidden="true">${ico}</span>${t(ROUTES[route].navKey)}
      </a>`).join("")}
  `).join("");
}

function renderChrome() {
  document.getElementById("brand-sub").textContent = t("brand.product");
  document.getElementById("sidebar-note").innerHTML = t("shell.read_only");
  document.getElementById("lbl-theme").textContent = t("shell.theme");
  document.getElementById("lbl-lang").textContent = t("shell.language");
  document.getElementById("menu-label").textContent = t("shell.menu");

  const themeSel = document.getElementById("theme-select");
  themeSel.innerHTML = THEMES.map((v) =>
    `<option value="${v}">${t(`theme.${v}`)}</option>`).join("");
  themeSel.value = getTheme();

  const langSel = document.getElementById("lang-select");
  langSel.innerHTML = LOCALES.map((v) =>
    `<option value="${v}">${LOCALE_LABELS[v]}</option>`).join("");
  langSel.value = getLocale();

  renderNav();
}

async function route() {
  const root = document.getElementById("app");
  const name = currentRoute();
  renderNav();
  document.getElementById("sidebar").classList.remove("open");
  try {
    await ROUTES[name].render(root);
    root.focus({ preventScroll: true });
  } catch (err) {
    root.innerHTML = `<div class="empty">${t("common.load_error")}<span class="empty-hint">${String(err)}</span></div>`;
  }
}

function boot() {
  renderChrome();
  route();

  document.getElementById("theme-select").addEventListener("change", (e) => setTheme(e.target.value));
  document.getElementById("lang-select").addEventListener("change", async (e) => {
    await setLocale(e.target.value);
  });
  document.getElementById("menu-toggle").addEventListener("click", () => {
    const sb = document.getElementById("sidebar");
    const open = sb.classList.toggle("open");
    document.getElementById("menu-toggle").setAttribute("aria-expanded", String(open));
  });

  window.addEventListener("hashchange", route);
  // Re-render chrome + current page on language change (no reload).
  document.addEventListener("locale-changed", () => { renderChrome(); route(); });
}

initI18n().then(() => { initTheme(); boot(); });
