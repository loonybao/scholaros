/* Application Pipeline — kanban by stage with the S8a.1 working controls:
   start preparing, an optimistic document checklist, an inline plan editor,
   mark submitted (with confirmation), an audited "correct submission status"
   reopen, and a readable activity history. Deadlines and links stay inherited
   from the vacancy. Only manual-layer Application fields are written, through
   the safe endpoints; stage rules and the correction flow are enforced
   server-side. Writes update in place (no full-route reload for a checkbox);
   stage changes wait for confirmed server success. */

import { fmtDate, fmtDateTime } from "../format.js";
import { t } from "../i18n.js";
import { stageLabel } from "../labels.js";
import { badge, emptyState, esc, fetchJSON, pageHeader, panel, sourceLink } from "../ui.js";
import { ApiError, busy, guard, modalForm, patch, post, toast } from "../write.js";

const STAGES = ["identified", "preparing", "submitted", "monitoring",
  "awaiting_response", "interview", "offered", "rejected", "withdrawn"];
const ALWAYS_SHOWN = ["identified", "preparing", "submitted"];

let _byId = {};      // id -> app row (current server state)
let _root = null;
const url = (id) => `/api/applications/${encodeURIComponent(id)}`;
const reload = () => load(_root);

/* ---------- checklist (optimistic, no full reload) ---------- */
function materialLi(mat, id, idx) {
  const done = mat.status === "final";
  return `<li>
    <button class="check ${done ? "done" : ""}" data-act="toggle-mat" data-id="${esc(id)}" data-idx="${idx}" aria-pressed="${done}">
      <span class="check-box" aria-hidden="true">${done ? "☑" : "☐"}</span> <span class="check-name">${esc(mat.name)}</span>
    </button>
    ${badge(done ? t("app.mark_done") : t("app.mark_todo"), done ? "good" : "neutral")}
  </li>`;
}
function setMaterialDom(btn, done) {
  btn.classList.toggle("done", done);
  btn.setAttribute("aria-pressed", String(done));
  btn.querySelector(".check-box").textContent = done ? "☑" : "☐";
  const b = btn.parentElement.querySelector(".badge");
  if (b) { b.textContent = done ? t("app.mark_done") : t("app.mark_todo"); b.className = `badge tone-${done ? "good" : "neutral"}`; }
}
async function toggleMaterial(btn, id) {
  const a = _byId[id];
  if (!a || btn.disabled) return;
  const idx = Number(btn.dataset.idx);
  const prevDone = a.materials[idx].status === "final";
  const mats = a.materials.map((m) => ({ name: m.name, status: m.status, path: m.path || null }));
  mats[idx].status = prevDone ? "todo" : "final";
  btn.disabled = true;
  setMaterialDom(btn, !prevDone);                       // optimistic
  try {
    const r = await patch(url(id), { expected_updated_at: a.updated_at, materials: mats });
    a.materials = mats;
    a.updated_at = r.updated_at;
    if (r.warning) toast(t("act.reconcile"), "warn");
  } catch (e) {
    setMaterialDom(btn, prevDone);                      // revert on failure
    if (e instanceof ApiError && e.status === 409) { toast(t("act.stale"), "warn"); reload(); }
    else toast(t("act.error", { msg: e instanceof ApiError ? e.detail : String(e) }), "danger");
  } finally {
    btn.disabled = false;
  }
}

/* ---------- activity history ---------- */
function eventLabel(e) {
  if (e.event === "stage") return t("app.event.stage", { stage: stageLabel(e.note) });
  // Back-compat: earlier records used a "stage:<name>" event key.
  if (e.event.startsWith("stage:")) return t("app.event.stage", { stage: stageLabel(e.event.slice(6)) });
  return t(`app.event.${e.event}`);
}
function eventDetail(e) {
  return e.event === "stage" ? "" : (e.note || "");
}
function history(a) {
  if (!a.events || !a.events.length) return "";
  const rows = a.events.map((e) => `<li>
    <span class="ev-when">${esc(fmtDateTime(e.ts))}</span>
    <span class="ev-label">${esc(eventLabel(e))}</span>
    ${eventDetail(e) ? `<span class="ev-detail">${esc(eventDetail(e))}</span>` : ""}
  </li>`).join("");
  return `<details class="app-history"><summary>${t("app.history")}</summary><ul class="timeline">${rows}</ul></details>`;
}

/* ---------- card ---------- */
function editor(a) {
  return `<form class="app-editor" data-id="${esc(a.id)}" hidden>
    <label class="modal-field"><span>${t("app.internal_due")}</span>
      <input type="date" name="internal_due_date" value="${esc(a.internal_due_date || "")}"></label>
    <label class="modal-field"><span>${t("app.next_step")}</span>
      <input type="text" name="next_step" value="${esc(a.next_step || "")}"></label>
    <label class="modal-field"><span>${t("detail.notes")}</span>
      <textarea name="notes" rows="2">${esc(a.notes || "")}</textarea></label>
    <div class="modal-actions">
      <button type="button" class="btn ghost sm" data-act="cancel-edit" data-id="${esc(a.id)}">${t("act.cancel")}</button>
      <button type="submit" class="btn secondary sm">${t("act.save")}</button>
    </div>
  </form>`;
}

function card(a) {
  _byId[a.id] = a;
  const blockers = a.blockers.length ? `<ul class="blockers">${a.blockers.map((b) => `<li>${esc(b)}</li>`).join("")}</ul>` : "";
  const checklist = a.materials.length
    ? `<div class="app-checklist"><h4>${t("app.checklist")}</h4><ul class="checklist">${a.materials.map((m, i) => materialLi(m, a.id, i)).join("")}</ul></div>` : "";
  const submitted = a.submitted_at
    ? `<div class="app-submitted">${badge(t("app.submitted_on", { date: fmtDate(a.submitted_at) }), "good")}
        ${a.portal_reference ? `<span class="muted">${t("app.portal_ref", { ref: a.portal_reference })}</span>` : ""}</div>`
    : "";
  const acts = [];
  if (a.stage === "identified")
    acts.push(`<button class="btn primary sm" data-act="start" data-id="${esc(a.id)}">${t("act.start_preparing")}</button>`);
  if (a.stage === "preparing" || a.stage === "monitoring") {
    acts.push(`<button class="btn ghost sm" data-act="add-doc" data-id="${esc(a.id)}">${t("app.add_document")}</button>`);
    acts.push(`<button class="btn secondary sm" data-act="submit" data-id="${esc(a.id)}">${t("act.mark_submitted")}</button>`);
  }
  if (a.stage === "submitted")
    acts.push(`<button class="btn secondary sm" data-act="correct" data-id="${esc(a.id)}">${t("act.correct_submission")}</button>`);
  acts.push(`<button class="btn ghost sm" data-act="edit" data-id="${esc(a.id)}" title="${t("act.save")}">✎</button>`);

  return `<div class="kanban-card" data-id="${esc(a.id)}">
    <div class="k-title">${esc(a.opportunity_title)}</div>
    <div class="k-meta">${a.official_deadline ? `${t("app.deadline")}: <strong>${esc(fmtDate(a.official_deadline))}</strong>` : t("common.none")}
      ${a.internal_due_date ? ` · ${t("app.internal")}: ${esc(fmtDate(a.internal_due_date))}` : ""}</div>
    ${a.next_step ? `<div class="k-next">${t("app.next")}: ${esc(a.next_step)}${a.next_step_due ? ` (${esc(fmtDate(a.next_step_due))})` : ""}</div>` : ""}
    ${blockers}
    ${checklist}
    ${submitted}
    ${a.official_url ? `<div>${sourceLink(a.official_url, "app.official_page")}</div>` : ""}
    <div class="k-actions">${acts.join("")}</div>
    ${history(a)}
    ${editor(a)}
  </div>`;
}

/* ---------- stage / doc actions (wait for confirmed success) ---------- */
async function startPreparing(el, id) {
  const a = _byId[id];
  await busy(el, () => guard(() => patch(url(id), { expected_updated_at: a.updated_at, stage: "preparing" }),
    { onDone: reload, success: t("act.saved") }));
}
async function addDoc(el, id) {
  const a = _byId[id];
  const vals = await modalForm({ title: t("app.add_document"),
    fields: [{ name: "name", label: t("app.doc_name"), type: "text" }] });
  if (!vals || !vals.name) return;
  const mats = a.materials.map((m) => ({ name: m.name, status: m.status, path: m.path || null }));
  mats.push({ name: vals.name, status: "todo", path: null });
  await busy(el, () => guard(() => patch(url(id), { expected_updated_at: a.updated_at, materials: mats }),
    { onDone: reload, success: t("act.saved") }));
}
async function markSubmitted(el, id) {
  const a = _byId[id];
  const vals = await modalForm({
    title: t("app.submit.title"), submitLabel: t("act.mark_submitted"),
    fields: [
      { name: "submitted_at", label: t("app.submit.date"), type: "date", value: new Date().toISOString().slice(0, 10) },
      { name: "confirm", label: t("app.submit.confirm"), type: "checkbox" },
      { name: "documents_used", label: t("app.submit.docs"), type: "text" },
      { name: "portal_reference", label: t("app.submit.portal"), type: "text" },
    ],
  });
  if (!vals || !vals.confirm || !vals.submitted_at) return;
  const body = { stage: "submitted", confirm_submitted: true, submitted_at: vals.submitted_at,
    expected_updated_at: a.updated_at,
    documents_used: vals.documents_used ? vals.documents_used.split(",").map((x) => x.trim()).filter(Boolean) : [] };
  if (vals.portal_reference) body.portal_reference = vals.portal_reference;
  await busy(el, () => guard(() => patch(url(id), body), { onDone: reload, success: t("act.saved") }));
}
async function correctSubmission(el, id) {
  const a = _byId[id];
  const vals = await modalForm({
    title: t("app.correct.title"), submitLabel: t("act.correct_submission"),
    fields: [
      { name: "info", type: "note", label: t("app.correct.current", { date: a.submitted_at ? fmtDate(a.submitted_at) : "" }) },
      { name: "correction_reason", label: t("app.correct.reason"), type: "textarea" },
      { name: "confirm", label: t("app.correct.confirm"), type: "checkbox" },
    ],
  });
  if (!vals || !vals.correction_reason || !vals.confirm) return;
  await busy(el, () => guard(() => post(`${url(id)}/correct-submission`,
    { expected_updated_at: a.updated_at, correction_reason: vals.correction_reason, confirm: true }),
    { onDone: reload, success: t("act.saved") }));
}
function toggleEditor(id, show) {
  const form = _root.querySelector(`form.app-editor[data-id="${CSS.escape(id)}"]`);
  if (form) form.hidden = show === undefined ? !form.hidden : !show;
}
async function saveEditor(form) {
  const id = form.dataset.id, a = _byId[id];
  const body = { expected_updated_at: a.updated_at,
    internal_due_date: form.internal_due_date.value || null,
    next_step: form.next_step.value, notes: form.notes.value };
  await busy(form.querySelector('button[type="submit"]'),
    () => guard(() => patch(url(id), body), { onDone: reload, success: t("act.saved") }));
}

function wire(root) {
  root.onclick = (e) => {
    const el = e.target.closest("[data-act]");
    if (!el) return;
    const { act, id } = el.dataset;
    if (act === "toggle-mat") return toggleMaterial(el, id);
    if (act === "start") return startPreparing(el, id);
    if (act === "add-doc") return addDoc(el, id);
    if (act === "submit") return markSubmitted(el, id);
    if (act === "correct") return correctSubmission(el, id);
    if (act === "edit") return toggleEditor(id);
    if (act === "cancel-edit") return toggleEditor(id, false);
  };
  root.onsubmit = (e) => {
    const form = e.target.closest("form.app-editor");
    if (form) { e.preventDefault(); saveEditor(form); }
  };
}

async function load(root) {
  _root = root;
  _byId = {};
  const data = await fetchJSON("/api/applications");
  const cols = STAGES.filter((s) => (data.stages[s] || []).length || ALWAYS_SHOWN.includes(s))
    .map((s) => `<div class="kanban-col"><h3>${stageLabel(s)} (${(data.stages[s] || []).length})</h3>
      ${(data.stages[s] || []).map(card).join("") || `<div class="empty">${t("common.none")}</div>`}</div>`).join("");
  root.innerHTML = pageHeader(t("app.title"), t("app.subtitle", { n: data.total })) +
    (data.total ? `<section class="panel"><div class="kanban">${cols}</div></section>`
      : panel("", emptyState(t("app.none"))));
  wire(root);
}

export default async function render(root) {
  await load(root);
}
