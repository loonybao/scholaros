/* Reviews — weekly decision reviews. None are generated yet. */

import { t } from "../i18n.js";
import { emptyState, pageHeader, panel } from "../ui.js";

export default async function render(root) {
  root.innerHTML = pageHeader(t("reviews.title"), t("reviews.subtitle")) +
    panel("", emptyState(t("reviews.none")));
}
