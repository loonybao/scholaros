/* Research Compass dashboard (S2, read-only).
   One render function per panel; all data from /api/dashboard + /api/health.
   Nothing is hard-coded: every row comes from the SQLite index over canonical. */

"use strict";

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));

const badge = (text, kind) =>
  `<span class="badge badge-${esc(kind)}">${esc(text)}</span>`;

const gateBadge = (gate) => badge(`gate: ${gate}`, gate);
const urgencyBadge = (urgency, days) => {
  const label = days === null || days === undefined
    ? "no deadline"
    : `${days}d left — ${urgency}`;
  return badge(label, urgency);
};
const fitText = (row) =>
  row.fit_overall === null || row.fit_overall === undefined
    ? "not analyzed"
    : `fit ${row.fit_overall}`;

function nextAction(row) {
  if (row.needs_review) return "Resolve manual review (see queue below)";
  if (row.urgency === "urgent" || row.urgency === "high")
    return "Verify posting and start application preparation";
  return "Monitor";
}

/* ---------------- panels ---------------- */

function renderHeader(dash) {
  document.getElementById("header-meta").textContent =
    `Generated ${dash.generated_at} · canonical → SQLite index → this page`;
}

function renderActionRequired(dash) {
  const el = document.getElementById("action-cards");
  const rows = dash.action_required;
  if (!rows.length) {
    el.innerHTML = '<div class="empty">Nothing needs action right now.</div>';
    return;
  }
  el.innerHTML = rows
    .map(
      (r) => `
      <div class="card">
        <div class="card-title">${esc(r.title)}</div>
        <div class="card-org">${esc(r.org_name || r.org_id)} · ${esc(r.location || "location unknown")}</div>
        <div class="card-row">
          ${urgencyBadge(r.urgency, r.days_to_deadline)}
          ${gateBadge(r.eligibility_gate)}
          ${r.needs_review ? badge("needs review", "review") : ""}
        </div>
        <div class="card-row">Deadline: ${esc(r.deadline || "unknown")} · ${esc(fitText(r))}</div>
        <div class="card-action">Next: ${esc(nextAction(r))}</div>
      </div>`
    )
    .join("");
}

function renderOpenTable(dash) {
  const el = document.getElementById("open-table");
  const rows = dash.open_opportunities;
  if (!rows.length) {
    el.innerHTML = '<tr><td class="empty">No open opportunities.</td></tr>';
    return;
  }
  const header =
    "<tr><th>Opportunity</th><th>Organisation</th><th>Deadline</th>" +
    "<th>Days</th><th>Gate</th><th>Fit</th><th>Status</th></tr>";
  const body = rows
    .map(
      (r) => `
      <tr>
        <td><a href="${esc(r.canonical_url)}" target="_blank" rel="noopener">${esc(r.title)}</a></td>
        <td>${esc(r.org_name || r.org_id)}</td>
        <td class="num">${esc(r.deadline || "—")}</td>
        <td class="num">${r.days_to_deadline ?? "—"}</td>
        <td>${gateBadge(r.eligibility_gate)}</td>
        <td class="num">${r.fit_overall ?? "—"}</td>
        <td>${esc(r.status)}</td>
      </tr>`
    )
    .join("");
  el.innerHTML = header + body;
}

function renderDeadlines(dash) {
  const el = document.getElementById("deadline-list");
  const rows = dash.upcoming_deadlines;
  if (!rows.length) {
    el.innerHTML = '<li class="empty">No deadlines within 45 days.</li>';
    return;
  }
  el.innerHTML = rows
    .map(
      (r) => `
      <li>
        <span>${esc(r.title)}</span>
        <span>${esc(r.deadline)} ${urgencyBadge(r.urgency, r.days_to_deadline)}</span>
      </li>`
    )
    .join("");
}

function renderReviewQueue(dash) {
  const el = document.getElementById("review-list");
  const rows = dash.review_queue;
  if (!rows.length) {
    el.innerHTML = '<div class="empty">Queue is empty.</div>';
    return;
  }
  el.innerHTML = rows
    .map(
      (r) => `
      <div class="review-item">
        <strong>${esc(r.title)}</strong> ${gateBadge(r.eligibility_gate)}
        <ul class="review-reasons">
          ${r.eligibility_reasons.map((x) => `<li>${esc(x)}</li>`).join("")}
        </ul>
      </div>`
    )
    .join("");
}

function renderHealth(health) {
  const el = document.getElementById("health");
  const counts = health.entity_counts || {};
  const items = [
    ["Opportunities", counts.opportunity ?? 0],
    ["Organisations", counts.organisation ?? 0],
    ["People", counts.person ?? 0],
    ["Signals", counts.signal ?? 0],
    ["Applications", counts.application ?? 0],
  ]
    .map(
      ([k, v]) =>
        `<div class="health-item"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div></div>`
    )
    .join("");

  const collectorNames = Object.keys(health.collectors || {});
  const collectors = collectorNames.length
    ? collectorNames
        .map((name) => {
          const c = health.collectors[name];
          const ok = (c.consecutive_errors || 0) === 0 && c.last_success;
          return `<div class="health-item"><div class="k">${esc(name)}</div>
            <div class="v">${badge(ok ? `ok · ${c.last_success}` : `errors: ${c.consecutive_errors || "never ran"}`, ok ? "pass" : "fail")}</div></div>`;
        })
        .join("")
    : `<div class="health-item"><div class="k">Collectors</div>
       <div class="v">${badge("none yet (S3)", "none")}</div></div>`;

  const llm = `<div class="health-item"><div class="k">LLM analysis</div>
    <div class="v">${badge(health.llm_configured ? "configured" : "not configured (S4)", health.llm_configured ? "pass" : "none")}</div></div>`;

  el.innerHTML = items + collectors + llm;

  document.getElementById("footer").textContent =
    `Index rebuilt: ${health.index_rebuilt_at || "never"} · ` +
    "Read-only dashboard (S2) — decisions and applications are edited via CLI until S4/S6.";
}

/* ---------------- boot ---------------- */

async function boot() {
  const [dash, health] = await Promise.all([
    fetch("/api/dashboard").then((r) => r.json()),
    fetch("/api/health").then((r) => r.json()),
  ]);
  renderHeader(dash);
  renderActionRequired(dash);
  renderOpenTable(dash);
  renderDeadlines(dash);
  renderReviewQueue(dash);
  renderHealth(health);
}

boot().catch((err) => {
  document.getElementById("header-meta").textContent =
    "Failed to load dashboard data: " + err;
});
