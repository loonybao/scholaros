/* Data Health (System) — collectors, index and entity counts. The engineering
   detail that used to sit on the Dashboard lives here. */

import { fmtDateTime } from "../format.js";
import { t } from "../i18n.js";
import { badge, esc, fetchJSON, pageHeader, panel } from "../ui.js";

export default async function render(root) {
  const h = await fetchJSON("/api/health");
  const counts = h.entity_counts || {};
  const entityRows = Object.entries(counts).map(([k, v]) =>
    `<tr><td>${esc(k)}</td><td class="num">${v}</td></tr>`).join("");

  const names = Object.keys(h.collectors || {});
  const collectors = names.length ? names.map((name) => {
    const c = h.collectors[name];
    const ok = (c.consecutive_errors || 0) === 0 && c.last_success;
    return `<tr><td>${esc(name)}</td>
      <td>${ok ? badge(`${t("sys.health.ok")} · ${esc(c.last_success ? fmtDateTime(c.last_success) : "")}`, "good")
        : badge(`${t("sys.health.errors")}: ${c.consecutive_errors || 0}`, "danger")}</td></tr>`;
  }).join("") : `<tr><td colspan="2" class="muted">${t("sys.health.never_run")}</td></tr>`;

  const reconcile = h.reconcile || [];
  const reconcileBanner = reconcile.length
    ? `<section class="panel attention"><h2>${t("sys.health.reconcile_title")}</h2>
        <p>${t("sys.health.reconcile", { n: reconcile.length })}</p>
        <ul>${reconcile.slice(-5).map((r) => `<li>${badge(esc(r.kind), "warn")} ${esc(r.id)} <span class="muted">${esc((r.at || "").slice(0, 16).replace("T", " "))}</span></li>`).join("")}</ul>
        <code>python -m compass rebuild-index &amp;&amp; python -m compass export</code></section>`
    : "";

  root.innerHTML = pageHeader(t("sys.health.title"), t("sys.health.subtitle")) +
    reconcileBanner +
    panel(t("sys.health.collectors"), `<div class="table-wrap"><table>${collectors}</table></div>`) +
    panel(t("sys.health.entities"), `<div class="table-wrap"><table>${entityRows}</table></div>`) +
    panel("", `<div class="status-line">
      <span><span class="k">${t("sys.health.rebuilt")}</span>${esc(fmtDateTime(h.index_rebuilt_at) || t("sys.health.never_run"))}</span>
      <span><span class="k">${t("sys.health.llm")}</span>${badge(h.llm_configured ? t("sys.health.llm_configured") : t("sys.health.llm_interactive"), "neutral")}</span>
    </div><p class="muted" style="margin-top:10px">${t("sys.health.pipeline")}</p>`);
}
