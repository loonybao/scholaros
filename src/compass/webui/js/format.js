/* Locale-aware date/number formatting via Intl. */

"use strict";

import { getLocale } from "./i18n.js";

const INTL_LOCALE = { "en": "en-GB", "zh-CN": "zh-CN", "zh-MY": "zh-Hans-MY" };

function intlLocale() { return INTL_LOCALE[getLocale()] || "en-GB"; }

function toDate(iso) {
  if (!iso) return null;
  // Date-only strings are parsed as local midnight to avoid TZ shifts.
  const d = new Date(iso.length <= 10 ? `${iso}T00:00:00` : iso);
  return isNaN(d.getTime()) ? null : d;
}

export function fmtDate(iso) {
  const d = toDate(iso);
  if (!d) return iso || "";
  return new Intl.DateTimeFormat(intlLocale(),
    { year: "numeric", month: "short", day: "numeric" }).format(d);
}

export function fmtMonthYear(iso) {
  const d = toDate(iso);
  if (!d) return iso || "";
  return new Intl.DateTimeFormat(intlLocale(),
    { year: "numeric", month: "long" }).format(d);
}

export function fmtDateTime(iso) {
  const d = toDate(iso);
  if (!d) return iso || "";
  return new Intl.DateTimeFormat(intlLocale(),
    { year: "numeric", month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit" }).format(d);
}

export function fmtNumber(n) {
  return new Intl.NumberFormat(intlLocale()).format(n);
}
