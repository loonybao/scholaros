/* Shared write helpers for the S8a interactive controls. All writes flow
   through the safe web endpoints (manual layer / Application / Action only);
   this module only adds JSON plumbing, typed errors, transient toasts and a
   minimal modal form. It never bypasses server-side ownership or transition
   checks — those live in webwrite.py. */

"use strict";

import { t } from "./i18n.js";
import { esc } from "./ui.js";

export class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === "string" ? detail : String(status));
    this.status = status;
    this.detail = detail;
  }
}

export async function api(method, url, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const resp = await fetch(url, opts);
  let data = null;
  try { data = await resp.json(); } catch { /* no body */ }
  if (!resp.ok) {
    const detail = data && (data.detail ?? data.message);
    throw new ApiError(resp.status, typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

export const post = (url, body) => api("POST", url, body);
export const patch = (url, body) => api("PATCH", url, body);

let _toastTimer = null;
export function toast(message, tone = "info") {
  const host = document.getElementById("toast-host");
  if (!host) return;
  host.innerHTML = `<div class="toast tone-${esc(tone)}" role="status">${esc(message)}</div>`;
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => { host.innerHTML = ""; }, 3400);
}

/** Run an async write; toast success or a typed error. On a 409 stale write we
    tell the user and still run onDone(null) so the caller can reload from the
    server. Returns the result, or null on any failure. */
export async function guard(fn, { onDone, success } = {}) {
  try {
    const r = await fn();
    if (success) toast(success, "good");
    if (onDone) await onDone(r);
    return r;
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) {
      toast(t("act.stale"), "warn");
      if (onDone) await onDone(null);
    } else {
      toast(t("act.error", { msg: e instanceof ApiError ? e.detail : String(e) }), "danger");
    }
    return null;
  }
}

/** Minimal modal form. `fields` describe the inputs; resolves to a values
    object on submit or null on cancel. Keyboard: Esc cancels. */
export function modalForm({ title, fields, submitLabel }) {
  return new Promise((resolve) => {
    const host = document.getElementById("modal-host");
    const inputId = (name) => `mf-${name}`;
    const rows = fields.map((f) => {
      const id = inputId(f.name);
      if (f.type === "checkbox")
        return `<label class="modal-check"><input type="checkbox" id="${id}" ${f.value ? "checked" : ""}> <span>${esc(f.label)}</span></label>`;
      if (f.type === "textarea")
        return `<label class="modal-field"><span>${esc(f.label)}</span><textarea id="${id}" rows="3" placeholder="${esc(f.placeholder || "")}">${esc(f.value || "")}</textarea></label>`;
      if (f.type === "select")
        return `<label class="modal-field"><span>${esc(f.label)}</span><select id="${id}">${f.options.map((o) => `<option value="${esc(o.value)}" ${o.value === f.value ? "selected" : ""}>${esc(o.label)}</option>`).join("")}</select></label>`;
      return `<label class="modal-field"><span>${esc(f.label)}</span><input type="${f.type || "text"}" id="${id}" value="${esc(f.value ?? "")}" placeholder="${esc(f.placeholder || "")}"></label>`;
    }).join("");

    host.innerHTML = `<div class="modal-backdrop"><form class="modal" id="modal-form" role="dialog" aria-modal="true">
      <h2>${esc(title)}</h2>${rows}
      <div class="modal-actions">
        <button type="button" class="btn ghost" id="modal-cancel">${esc(t("act.cancel"))}</button>
        <button type="submit" class="btn primary">${esc(submitLabel || t("act.save"))}</button>
      </div></form></div>`;
    host.hidden = false;

    const close = (result) => {
      host.hidden = true;
      host.innerHTML = "";
      document.removeEventListener("keydown", onKey);
      resolve(result);
    };
    const onKey = (e) => { if (e.key === "Escape") close(null); };
    document.addEventListener("keydown", onKey);
    host.querySelector("#modal-cancel").addEventListener("click", () => close(null));
    host.querySelector(".modal-backdrop").addEventListener("mousedown", (e) => {
      if (e.target.classList.contains("modal-backdrop")) close(null);
    });
    host.querySelector("#modal-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const out = {};
      for (const f of fields) {
        const el = document.getElementById(inputId(f.name));
        out[f.name] = f.type === "checkbox" ? el.checked : el.value.trim();
      }
      close(out);
    });
    const first = host.querySelector("input, textarea, select");
    if (first) first.focus();
  });
}
