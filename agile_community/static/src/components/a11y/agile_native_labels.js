import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";

const ROOT = ".o_agile_backlog_list_view";

/**
 * Odoo's own search panel draws two icon-only buttons with no name (the fold caret of each
 * category and the button that opens the panel). Give them one so a screen reader can say what
 * they do. Safe to call repeatedly: only unnamed buttons are touched.
 */
export function labelNativeControls(root) {
    for (const button of root.querySelectorAll(".o_search_panel .o_toggle_fold:not([aria-label])")) {
        const title = button.parentElement
            ?.querySelector(".o_search_panel_label_title")
            ?.textContent?.trim();
        button.setAttribute("aria-label", title ? _t("Show or hide %s", title) : _t("Show or hide"));
    }
    for (const icon of root.querySelectorAll("button > i.oi-panel-right")) {
        const button = icon.parentElement;
        if (!button.hasAttribute("aria-label")) {
            button.setAttribute("aria-label", _t("Show or hide the filter panel"));
        }
    }
}

export const agileNativeLabels = {
    start() {
        let queued = false;
        const run = () => {
            queued = false;
            for (const root of document.querySelectorAll(ROOT)) {
                labelNativeControls(root);
            }
        };
        const observer = new MutationObserver(() => {
            if (!queued) {
                queued = true;
                requestAnimationFrame(run);
            }
        });
        observer.observe(document.body, { childList: true, subtree: true });
    },
};

registry.category("services").add("agile_native_labels", agileNativeLabels);
