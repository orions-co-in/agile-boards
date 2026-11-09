import { useEffect } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { patch } from "@web/core/utils/patch";
import { Notebook } from "@web/core/notebook/notebook";

const STORAGE_KEY = "agile_project_form_tab";

/** The tab the person last used on a project form, kept in this browser. */
export function readProjectTab() {
    try {
        return browser.localStorage.getItem(STORAGE_KEY) || null;
    } catch {
        // Private windows can refuse storage; the form then opens on its first tab.
        return null;
    }
}

export function rememberProjectTab(page) {
    try {
        if (page) {
            browser.localStorage.setItem(STORAGE_KEY, page);
        }
    } catch {
        // Nothing to do: remembering the tab is a convenience.
    }
}

/** Reloading the project form keeps the tab you were on instead of going back to Description (U-1). */
patch(Notebook.prototype, {
    setup() {
        super.setup(...arguments);
        const config = this.env.model?.config;
        if (config?.resModel !== "project.project") {
            return;
        }
        // Pages are numbered (page_4), which shifts when a project hides a tab; the page name is stable.
        const nameOf = (id) => this.pages.find(([pageId]) => pageId === id)?.[1].name;
        const saved = readProjectTab();
        const match = this.pages.find(([, page]) => page.name === saved && page.isVisible);
        if (saved && match) {
            this.state.currentPage = match[0];
        }
        useEffect(
            () => rememberProjectTab(nameOf(this.state.currentPage)),
            () => [this.state.currentPage]
        );
    },
});
