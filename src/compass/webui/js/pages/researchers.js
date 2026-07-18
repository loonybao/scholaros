/* Researchers — people linked to target groups (read-only). */

import { t } from "../i18n.js";
import { contactLabel } from "../labels.js";
import { badge, emptyState, esc, fetchJSON, pageHeader, panel } from "../ui.js";

export default async function render(root) {
  const data = await fetchJSON("/api/researchers");
  const rows = data.researchers;
  const body = rows.map((p) => `
    <tr>
      <td><strong>${esc(p.name)}</strong></td>
      <td>${esc((p.org_name || p.org_id || "").replace(/ \(.*\)$/, ""))}</td>
      <td>${esc(p.title || t("common.none"))}</td>
      <td>${badge(contactLabel(p.contact_status), "neutral")}</td>
    </tr>`).join("");
  root.innerHTML = pageHeader(t("researchers.title"), t("researchers.subtitle")) +
    (rows.length ? panel("", `<div class="table-wrap"><table>
      <tr><th>${t("researchers.col.name")}</th><th>${t("researchers.col.org")}</th>
      <th>${t("researchers.col.role")}</th><th>${t("researchers.col.contact")}</th></tr>${body}</table></div>`)
      : panel("", emptyState(t("researchers.none"))));
}
