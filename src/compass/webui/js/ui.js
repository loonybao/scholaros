/* Shared UI helpers. Colours never carry meaning alone — every badge has a
   text label. */

"use strict";

export const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));

export const badge = (text, kind) =>
  `<span class="badge badge-${esc(kind)}">${esc(text)}</span>`;

export const statusBadge = (text, cls) =>
  `<span class="badge ${esc(cls)}">${esc(text)}</span>`;

export const gateBadge = (gate) => badge(`gate: ${gate}`, gate);

export const urgencyBadge = (urgency, days) => {
  const label = days === null || days === undefined
    ? "no deadline"
    : `${days}d left — ${urgency}`;
  return badge(label, urgency);
};

export const fitText = (row) =>
  row.fit_overall === null || row.fit_overall === undefined
    ? "not analyzed"
    : `research fit ${row.fit_overall}` +
      (row.fit_type ? ` (${row.fit_type})` : "");

export const recommendationBadge = (row) => {
  if (!row.recommendation) return "";
  if (row.eligibility_gate === "fail")
    return badge("reject — eligibility failed", "fail");
  if (row.eligibility_gate === "uncertain" &&
      (row.recommendation === "apply" || row.recommendation === "consider"))
    return badge(
      `${row.recommendation} — pending eligibility verification`, "uncertain");
  return badge(row.recommendation, row.recommendation === "apply" ? "pass" : "none");
};

export const emptyState = (message, hint) =>
  `<div class="empty">${esc(message)}` +
  (hint ? `<span class="empty-hint">${esc(hint)}</span>` : "") +
  `</div>`;

export async function fetchJSON(url) {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`${url} -> ${resp.status}`);
  return resp.json();
}

export function panel(title, bodyHtml, id = "") {
  return `<section class="panel" ${id ? `id="${esc(id)}"` : ""}>
    <h2>${esc(title)}</h2>${bodyHtml}</section>`;
}
