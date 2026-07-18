/* Application Pipeline — kanban by stage, now with the S8a working controls:
   start preparing, toggle a document checklist, edit the internal plan, and
   mark submitted (with confirmation). Deadlines and links stay inherited from
   the vacancy. Only manual-layer Application fields are written, through the
   safe endpoints; stage transitions and the submitted-requires-confirmation
   rule are enforced server-side. */

import { fmtDate } from "../format.js";
import { t } from "../i18n.js";
import { stageLabel } from "../labels.js";
import { badge, emptyState, esc, fetchJSON, pageHeader, panel, sourceLink } from "../ui.js";
import { guard, modalForm, patch } from "../write.js";

const STAGES = ["identified", "preparing", "submitted", "monitoring",
  "awaiting_response", "interview", "offered", "rejected", "withdrawn"];
const ALWAYS_SHOWN = ["identified", "preparing", "submitted"];

let _byId = {};   // id -> app row from the latest render (current server state)

function materials(a) {
  if (!a.materials.length) return "";
  const items = a.materials.map((mat, i) => {
    const done = mat.status === "final";
    return `<li>
      <button class="check ${done ? "done" : ""}" data-act="toggle-mat" data-id="${esc(a.id)}" data-idx="${i}"
        aria-pressed="${done}">${done ? "☑" : "☐"} <span>${esc(mat.name)}</span></button>
      ${badge(done ? t("app.mark_done") : t("app.mark_todo"), done ? "good" : "neutral")}
    </li>`;
  }).join("");
  return `<div class="app-checklist"><h4>${t("app.checklist")}</h4><ul class="checklist">${items}</ul></div>`;
}

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
  acts.push(`<button class="btn ghost sm" data-act="edit" data-id="${esc(a.id)}">✎</button>`);

  return `<div class="kanban-card" data-id="${esc(a.id)}">
    <div class="k-title">${esc(a.opportunity_title)}</div>
    <div class="k-meta">${a.official_deadline ? `${t("app.deadline")}: <strong>${esc(fmtDate(a.official_deadline))}</strong>` : t("common.none")}
      ${a.internal_due_date ? ` · ${t("app.internal")}: ${esc(fmtDate(a.internal_due_date))}` : ""}</div>
    ${a.next_step ? `<div class="k-next">${t("app.next")}: ${esc(a.next_step)}${a.next_step_due ? ` (${esc(fmtDate(a.next_step_due))})` : ""}</div>` : ""}
    ${blockers}
    ${materials(a)}
    ${submitted}
    ${a.official_url ? `<div>${sourceLink(a.official_url, "app.official_page")}</div>` : ""}
    <div class="k-actions">${acts.join("")}</div>
    ${editor(a)}
  </div>`;
}

async function load(root) {
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

function wire(root) {
  const reload = () => load(root);
  const doPatch = (id, body, success) => {
    const a = _byId[id];
    return guard(() => patch(`/api/applications/${encodeURIComponent(id)}`,
      { expected_updated_at: a ? a.updated_at : null, ...body }),
      { onDone: reload, success });
  };

  root.querySelectorAll('[data-act="start"]').forEach((el) =>
    el.addEventListener("click", () => doPatch(el.dataset.id, { stage: "preparing" }, t("act.saved"))));

  root.querySelectorAll('[data-act="toggle-mat"]').forEach((el) =>
    el.addEventListener("click", () => {
      const a = _byId[el.dataset.id];
      if (!a) return;
      const mats = a.materials.map((m) => ({ name: m.name, status: m.status, path: m.path || null }));
      const i = Number(el.dataset.idx);
      mats[i].status = mats[i].status === "final" ? "todo" : "final";
      doPatch(el.dataset.id, { materials: mats });
    }));

  root.querySelectorAll('[data-act="add-doc"]').forEach((el) =>
    el.addEventListener("click", async () => {
      const a = _byId[el.dataset.id];
      if (!a) return;
      const vals = await modalForm({
        title: t("app.add_document"),
        fields: [{ name: "name", label: t("app.doc_name"), type: "text" }],
      });
      if (!vals || !vals.name) return;
      const mats = a.materials.map((m) => ({ name: m.name, status: m.status, path: m.path || null }));
      mats.push({ name: vals.name, status: "todo", path: null });
      doPatch(el.dataset.id, { materials: mats }, t("act.saved"));
    }));

  root.querySelectorAll('[data-act="submit"]').forEach((el) =>
    el.addEventListener("click", async () => {
      const vals = await modalForm({
        title: t("app.submit.title"),
        submitLabel: t("act.mark_submitted"),
        fields: [
          { name: "submitted_at", label: t("app.submit.date"), type: "date", value: new Date().toISOString().slice(0, 10) },
          { name: "confirm", label: t("app.submit.confirm"), type: "checkbox" },
          { name: "documents_used", label: t("app.submit.docs"), type: "text" },
          { name: "portal_reference", label: t("app.submit.portal"), type: "text" },
        ],
      });
      if (!vals || !vals.confirm || !vals.submitted_at) return;
      const body = {
        stage: "submitted", confirm_submitted: true, submitted_at: vals.submitted_at,
        documents_used: vals.documents_used ? vals.documents_used.split(",").map((x) => x.trim()).filter(Boolean) : [],
      };
      if (vals.portal_reference) body.portal_reference = vals.portal_reference;
      doPatch(el.dataset.id, body, t("act.saved"));
    }));

  // Inline plan editor (internal date / next step / notes).
  root.querySelectorAll('[data-act="edit"]').forEach((el) =>
    el.addEventListener("click", () => {
      const form = root.querySelector(`form.app-editor[data-id="${CSS.escape(el.dataset.id)}"]`);
      if (form) form.hidden = !form.hidden;
    }));
  root.querySelectorAll('[data-act="cancel-edit"]').forEach((el) =>
    el.addEventListener("click", () => {
      const form = root.querySelector(`form.app-editor[data-id="${CSS.escape(el.dataset.id)}"]`);
      if (form) form.hidden = true;
    }));
  root.querySelectorAll("form.app-editor").forEach((form) =>
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const id = form.dataset.id;
      const body = {
        internal_due_date: form.internal_due_date.value || null,
        next_step: form.next_step.value,
        notes: form.notes.value,
      };
      doPatch(id, body, t("act.saved"));
    }));
}

export default async function render(root) {
  await load(root);
}
