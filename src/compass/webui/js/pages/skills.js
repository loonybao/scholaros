/* Skills — a friendly, editable "my skills & learning" board (S8b) plus the
   demand radar (S6a) behind a toggle. The board reads the effective profile
   (baseline current_profile.yaml overlaid with audited SkillProgress); editing
   here writes SkillProgress only, never the baseline config. */

import { t } from "../i18n.js";
import {
  confidenceLabel, learningLabel, levelLabel, skillStatusLabel, skillTone,
} from "../labels.js";
import { badge, emptyState, esc, fetchJSON, pageHeader, panel } from "../ui.js";
import { busy, guard, put } from "../write.js";

const LEVELS = ["none", "beginner", "intermediate", "advanced"];
const LEARNING = ["not_started", "learning", "practicing", "proficient", "paused"];
const CONFIDENCE = ["low", "medium", "high"];

let data = null;
let _root = null;

/* ---------- board ---------- */
function levelBar(level, target) {
  const cur = LEVELS.indexOf(level || "none");
  const tgt = LEVELS.indexOf(target);
  const segs = [1, 2, 3].map((i) =>
    `<span class="lvl-seg ${cur >= i ? "on" : ""} ${tgt === i ? "target" : ""}"></span>`).join("");
  return `<div class="lvl-bar" aria-label="${esc(levelLabel(level) || t("label.level.none"))}">${segs}</div>`;
}

function selectField(name, label, cur, options, labelFn) {
  const opts = [`<option value="">${t("skills.field.keep")}</option>`].concat(
    options.map((v) => `<option value="${esc(v)}" ${v === cur ? "selected" : ""}>${esc(labelFn(v))}</option>`));
  return `<label class="modal-field"><span>${esc(label)}</span><select name="${name}">${opts.join("")}</select></label>`;
}

function editForm(s) {
  return `<form class="skill-edit" data-skill="${esc(s.skill)}" hidden>
    ${selectField("current_level", t("skills.field.level"), s.level, LEVELS, levelLabel)}
    ${selectField("learning_status", t("skills.field.learning"), s.learning_status, LEARNING, learningLabel)}
    ${selectField("target_level", t("skills.field.target"), s.target_level, LEVELS, levelLabel)}
    ${selectField("confidence", t("skills.field.confidence"), s.confidence, CONFIDENCE, confidenceLabel)}
    <label class="modal-field"><span>${t("skills.field.evidence")}</span><textarea name="evidence" rows="2">${esc(s.evidence || "")}</textarea></label>
    <label class="modal-field"><span>${t("skills.field.notes")}</span><textarea name="notes" rows="2">${esc(s.notes || "")}</textarea></label>
    <div class="modal-actions">
      <button type="button" class="btn ghost sm" data-act="cancel-skill" data-skill="${esc(s.skill)}">${t("act.cancel")}</button>
      <button type="submit" class="btn secondary sm">${t("act.save")}</button>
    </div>
  </form>`;
}

function skillCard(s) {
  const demand = (s.required_count + s.preferred_count) > 0
    ? t("skills.demand_req", { n: s.required_count + s.preferred_count })
    : t("skills.demand_none");
  return `<div class="skill-card" data-skill="${esc(s.skill)}">
    <div class="skill-card-head">
      <strong>${esc(s.label)}</strong>
      ${badge(s.tracked ? t("skills.tracked") : t("skills.baseline"), s.tracked ? "info" : "neutral")}
    </div>
    ${levelBar(s.level, s.target_level)}
    <div class="skill-card-meta">
      <span class="lvl-text">${esc(levelLabel(s.level) || t("label.level.none"))}${s.target_level ? ` <span class="muted">→ ${esc(levelLabel(s.target_level))}</span>` : ""}</span>
      ${s.learning_status ? badge(learningLabel(s.learning_status), "warn") : ""}
    </div>
    <div class="skill-card-foot">
      <span class="muted">${esc(demand)}</span>
      ${badge(skillStatusLabel(s.suggested_status), skillTone(s.suggested_status))}
    </div>
    <button class="btn ghost sm skill-edit-btn" data-act="edit-skill" data-skill="${esc(s.skill)}">${t("skills.edit")}</button>
    ${editForm(s)}
  </div>`;
}

function group(titleKey, cards) {
  if (!cards.length) return "";
  return `<div class="skill-group"><h3>${t(titleKey)} <span class="muted">(${cards.length})</span></h3>
    <div class="skill-grid">${cards.map(skillCard).join("")}</div></div>`;
}

function board() {
  const b = data.profile_board || [];
  if (!b.length) return panel(t("skills.board.title"), emptyState(t("skills.none_scope")));
  const strengths = b.filter((s) => s.suggested_status === "strength");
  const learn = b.filter((s) => s.suggested_status === "learn_next");
  const other = b.filter((s) => !["strength", "learn_next"].includes(s.suggested_status));
  return panel(t("skills.board.title"),
    `<p class="panel-lede">${t("skills.board.subtitle")}</p>` +
    group("skills.board.learn_next", learn) +
    group("skills.board.strengths", strengths) +
    group("skills.board.other", other));
}

/* ---------- demand radar (collapsed) ---------- */
function radarTable() {
  const rows = (b) => b.skills.map((s) => `<tr>
    <td><strong>${esc(s.label)}</strong></td>
    <td class="num">${s.required_count}</td><td class="num">${s.preferred_count}</td>
    <td class="num">${s.supporting.length}</td>
    <td>${esc(levelLabel(s.user_level) || t("common.none"))}</td>
    <td>${badge(skillStatusLabel(s.suggested_status), skillTone(s.suggested_status))}</td></tr>`).join("");
  const tm = data.scopes.target_market;
  return `<details class="radar-details"><summary>${t("skills.board.radar_toggle")}</summary>
    <p class="panel-lede">${t("skills.subtitle")}</p>
    <div class="table-wrap"><table>
      <tr><th>${t("skills.col.skill")}</th><th>${t("skills.col.required")}</th><th>${t("skills.col.preferred")}</th>
      <th>${t("skills.col.opportunities")}</th><th>${t("skills.col.level")}</th><th>${t("skills.col.status")}</th></tr>
      ${rows(tm) || `<tr><td colspan="6">${t("skills.none_scope")}</td></tr>`}</table></div>
  </details>`;
}

/* ---------- wiring ---------- */
function toggleForm(skill, show) {
  const f = _root.querySelector(`form.skill-edit[data-skill="${CSS.escape(skill)}"]`);
  if (f) f.hidden = show === undefined ? !f.hidden : !show;
}

async function saveSkill(form) {
  const skill = form.dataset.skill;
  const body = {};
  for (const name of ["current_level", "learning_status", "target_level", "confidence"]) {
    const v = form[name].value;
    if (v) body[name] = v;
  }
  body.evidence = form.evidence.value;
  body.notes = form.notes.value;
  await busy(form.querySelector('button[type="submit"]'),
    () => guard(() => put(`/api/skills/${encodeURIComponent(skill)}/progress`, body),
      { onDone: () => render(_root), success: t("act.saved") }));
}

function wire(root) {
  root.onclick = (e) => {
    const el = e.target.closest("[data-act]");
    if (!el) return;
    if (el.dataset.act === "edit-skill") return toggleForm(el.dataset.skill);
    if (el.dataset.act === "cancel-skill") return toggleForm(el.dataset.skill, false);
  };
  root.onsubmit = (e) => {
    const form = e.target.closest("form.skill-edit");
    if (form) { e.preventDefault(); saveSkill(form); }
  };
}

export default async function render(root) {
  _root = root;
  data = await fetchJSON("/api/skills");
  root.innerHTML = pageHeader(t("skills.title"), "") + board() + panel("", radarTable());
  wire(root);
}
