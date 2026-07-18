/* Hash router. Each page module exports a default async render(root, opts). */

import renderApplications from "./pages/applications.js";
import renderBrowser from "./pages/browser.js";
import renderDashboard from "./pages/dashboard.js";
import renderSkills from "./pages/skills.js";
import renderTargets from "./pages/targets.js";

const ROUTES = {
  dashboard: (root) => renderDashboard(root),
  skills: (root) => renderSkills(root),
  opportunities: (root) => renderBrowser(root, { archive: false }),
  targets: (root) => renderTargets(root),
  applications: (root) => renderApplications(root),
  archive: (root) => renderBrowser(root, { archive: true }),
};

function currentRoute() {
  const hash = window.location.hash.replace(/^#\/?/, "");
  const path = hash.split("?")[0];
  return ROUTES[path] ? path : "dashboard";
}

async function route() {
  const root = document.getElementById("app");
  const name = currentRoute();
  document.querySelectorAll("#nav .nav-item[data-route]").forEach((el) =>
    el.classList.toggle("active", el.dataset.route === name));
  try {
    await ROUTES[name](root);
  } catch (err) {
    root.innerHTML = `<div class="empty">Failed to load this view: ${String(err)}</div>`;
  }
}

window.addEventListener("hashchange", route);
route();
