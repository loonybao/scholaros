/* Shared UI helpers. Colour is never the only signal — every badge carries a
   text label. */

"use strict";

import { t } from "./i18n.js";

export const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));

/** Pill with a semantic tone: good | info | warn | danger | neutral. */
export const badge = (text, tone = "neutral") =>
  `<span class="badge tone-${esc(tone)}">${esc(text)}</span>`;

export const emptyState = (message, hint) =>
  `<div class="empty">${esc(message)}` +
  (hint ? `<span class="empty-hint">${esc(hint)}</span>` : "") + `</div>`;

export const panel = (title, bodyHtml, cls = "") =>
  `<section class="panel ${esc(cls)}">` +
  (title ? `<h2>${esc(title)}</h2>` : "") + bodyHtml + `</section>`;

export const pageHeader = (title, subtitle) =>
  `<header class="page-header"><h1>${esc(title)}</h1>` +
  (subtitle ? `<p class="header-meta">${esc(subtitle)}</p>` : "") + `</header>`;

export async function fetchJSON(url) {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`${url} -> ${resp.status}`);
  return resp.json();
}

/** External source link with a translated label. */
export const sourceLink = (url, key = "common.open") =>
  url ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(t(key))}</a>` : "";
