import { signal } from "@odoo/owl";
import { Component, onMounted, onWillUnmount, proxy, usePlugin, useProps, t } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useBus, useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { sidebarTarget, SIDEBAR_ENTRIES } from "@agile_community/sidebar/sidebar_helpers";
import { openShortcutHelp } from "@agile_community/shortcuts/agile_shortcuts";
import { PALETTE_ACTIONS, buildSections, isPaletteKey, matchTargets, moveIndex } from "./palette_helpers";

import { ActionPlugin } from "@web/webclient/actions/action_plugin";

const SEARCH_DELAY = 150;

/**
 * The command palette (K-1032): Ctrl+K, then type an issue key, a word of a title or the name of a screen.
 * With nothing typed it lists the last issues this person opened in the project. Every issue comes from a
 * server call that applies the person's own access, so the box never shows or confirms a hidden issue.
 */
export class AgilePalette extends Component {
    static template = "agile_community.Palette";
    static components = { Dialog };
    props = useProps({ close: t.function(), projectId: t.number(), entries: t.array()});

    setup() {
        this.orm = useService("orm");
        this.action = usePlugin(ActionPlugin);
        this.dialog = useService("dialog");
        this.inputRef = signal.ref();
        this.state = proxy({ term: "", issues: [], index: 0, loaded: false });
        this.timer = null;
        this.token = 0;
        this.screens = SIDEBAR_ENTRIES.filter((entry) => this.props.entries.includes(entry.key));
        onMounted(() => {
            this.inputRef()?.focus();
            this.search();
        });
        onWillUnmount(() => clearTimeout(this.timer));
    }

    get sections() {
        return this.built.sections;
    }

    get built() {
        const typed = this.state.term.trim();
        return buildSections({
            issues: this.state.issues,
            issuesTitle: typed ? _t("Issues") : _t("Recent issues"),
            screens: matchTargets(this.screens, typed),
            actions: matchTargets(PALETTE_ACTIONS, typed),
            projectId: this.props.projectId,
        });
    }

    get flat() {
        return this.built.flat;
    }

    rowId(item) {
        return `o_ag_palette_row_${item.index}`;
    }

    get activeId() {
        return this.flat.length ? `o_ag_palette_row_${this.state.index}` : "";
    }

    onInput(ev) {
        this.state.term = ev.target.value;
        this.state.index = 0;
        clearTimeout(this.timer);
        this.pending = true;
        this.timer = setTimeout(() => {
            this.pending = false;
            this.search();
        }, SEARCH_DELAY);
    }

    search() {
        this.running = this.fetchIssues();
        return this.running;
    }

    async fetchIssues() {
        const token = ++this.token;
        const term = this.state.term.trim();
        let issues = [];
        try {
            issues = term
                ? await this.orm.call("project.task", "agile_palette_search", [term, this.props.projectId])
                : await this.orm.call("project.task", "agile_palette_recent", [this.props.projectId]);
        } catch {
            issues = [];
        }
        if (token === this.token) {
            this.state.issues = issues;
            this.state.loaded = true;
            this.state.index = Math.min(this.state.index, Math.max(this.flat.length - 1, 0));
        }
    }

    onKeydown(ev) {
        if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
            ev.preventDefault();
            this.state.index = moveIndex(this.state.index, ev.key === "ArrowDown" ? 1 : -1, this.flat.length);
            document.getElementById(this.activeId)?.scrollIntoView({ block: "nearest" });
        } else if (ev.key === "Enter") {
            ev.preventDefault();
            this.chooseHighlighted();
        }
    }

    /** Enter right after typing waits for the answer to what was typed, so it never opens a stale row. */
    async chooseHighlighted() {
        if (this.pending) {
            clearTimeout(this.timer);
            this.pending = false;
            await this.search();
        } else {
            await this.running;
        }
        const item = this.flat[this.state.index];
        if (item) {
            this.choose(item);
        }
    }

    async choose(item) {
        // Services of a closed dialog stop answering, so fetch what is needed before closing.
        let action = null;
        if (item.type === "issue") {
            action = {
                type: "ir.actions.act_window",
                res_model: "project.task",
                res_id: item.issue.id,
                views: [[false, "form"]],
                target: "current",
                context: { default_project_id: item.issue.project_id || this.props.projectId },
            };
        } else if (item.type === "screen") {
            action = await this.orm.call("project.project", "agile_sidebar_action", [
                [this.props.projectId],
                item.screen.key,
            ]);
        }
        const { dialog, action: actionService } = this;
        this.props.close();
        if (action) {
            await actionService.doAction(action, item.type === "screen" ? { clearBreadcrumbs: true } : {});
        } else if (item.action.key === "shortcuts") {
            openShortcutHelp(dialog);
        }
    }
}

/**
 * Listens for Ctrl+K on project screens, opens the palette, and remembers the issues that are opened
 * (the form of an issue) so the palette can list them.
 */
export class AgilePaletteHost extends Component {
    static template = "agile_community.PaletteHost";
    props = useProps({});

    setup() {
        this.orm = useService("orm");
        this.action = usePlugin(ActionPlugin);
        this.dialog = useService("dialog");
        this.lastVisit = null;
        this.onKeydown = this.onKeydown.bind(this);
        onMounted(() => document.addEventListener("keydown", this.onKeydown));
        onWillUnmount(() => document.removeEventListener("keydown", this.onKeydown));
        useBus(this.env.bus, "ACTION_MANAGER:UI-UPDATED", () => this.remember());
    }

    /** Record the issue form that is now open; a failure here must never disturb the screen. */
    remember() {
        const controller = this.action.currentController;
        const resId = controller?.props?.resId;
        if (controller?.action?.res_model !== "project.task" || controller.props?.type !== "form" || !resId) {
            return;
        }
        if (this.lastVisit !== resId) {
            this.lastVisit = resId;
            this.orm.silent.call("project.task", "agile_palette_visit", [[resId]]).catch(() => {});
        }
    }

    /** The project of the open Agile screen: a sidebar screen, or an issue opened from one. */
    projectIdOfScreen() {
        const controller = this.action.currentController;
        const target = sidebarTarget(controller);
        if (target && document.querySelector(".o_ag_side")) {
            return target.projectId;
        }
        const action = controller?.action;
        return action?.res_model === "project.task" && action.target !== "new" ? action.context?.default_project_id : null;
    }

    async onKeydown(ev) {
        if (!isPaletteKey(ev) || document.querySelector(".modal.show, .modal-dialog")) {
            return;
        }
        const projectId = this.projectIdOfScreen();
        if (!projectId) {
            return;
        }
        ev.preventDefault();
        // Odoo's own command palette listens on the window; without this both would open (NU-15).
        ev.stopPropagation();
        let data;
        try {
            data = await this.orm.call("project.project", "agile_sidebar_data", [[projectId]]);
        } catch {
            return;
        }
        if (data.enabled) {
            this.dialog.add(AgilePalette, { projectId, entries: data.entries });
        }
    }
}

registry.category("main_components").add("agile_community.palette", { Component: AgilePaletteHost });
