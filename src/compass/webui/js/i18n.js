/* Central i18n. Single t(key, params) with English fallback and dev-mode
   missing-key logging. Locale persists in localStorage; changes apply without
   reload (pages re-render on the 'locale-changed' event). */

"use strict";

export const LOCALES = ["en", "zh-CN", "zh-MY"];
export const LOCALE_LABELS = { "en": "English", "zh-CN": "简体中文", "zh-MY": "大马中文" };
const DEV = true;                 // dev mode: log missing keys
const _missing = new Set();

let _en = {};                     // English base (fallback source)
let _loc = {};                    // active locale (empty for en)
let _active = "en";

async function _load(loc) {
  try {
    const r = await fetch(`/static/locales/${loc}.json`);
    return r.ok ? await r.json() : {};
  } catch {
    return {};
  }
}

export async function initI18n() {
  _en = await _load("en");
  const stored = localStorage.getItem("locale");
  await setLocale(LOCALES.includes(stored) ? stored : "en", { silent: true });
}

export async function setLocale(loc, { silent = false } = {}) {
  _active = LOCALES.includes(loc) ? loc : "en";
  _loc = _active === "en" ? {} : await _load(_active);
  localStorage.setItem("locale", _active);
  document.documentElement.setAttribute("lang", _active);
  if (!silent) document.dispatchEvent(new CustomEvent("locale-changed"));
}

export function getLocale() { return _active; }

export function t(key, params) {
  let s = _loc[key];
  if (s === undefined) {
    if (_active !== "en" && DEV && !_missing.has(key)) {
      _missing.add(key);
      console.warn(`[i18n] missing '${_active}' key, using English: ${key}`);
    }
    s = _en[key];
  }
  if (s === undefined) {
    if (DEV && !_missing.has(key)) {
      _missing.add(key);
      console.error(`[i18n] missing key in all locales: ${key}`);
    }
    return key;
  }
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      s = s.split(`{${k}}`).join(String(v));
    }
  }
  return s;
}

export function missingKeys() { return [..._missing]; }
