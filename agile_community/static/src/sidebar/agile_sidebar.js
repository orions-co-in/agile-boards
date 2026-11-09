import { Component, markup, onMounted, proxy, usePlugin, useProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { isDisplayStandalone } from "@web/core/browser/feature_detection";
import { useBus, useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { rememberProjectTab } from "@agile_community/form/project_tab_memory";
import { BOTTOM_KEYS, SIDEBAR_ENTRIES, sidebarTarget } from "./sidebar_helpers";
import { openShortcutHelp } from "@agile_community/shortcuts/agile_shortcuts";
import { ActionPlugin } from "@web/webclient/actions/action_plugin";

const BODY_CLASS = "o_ag_has_sidebar";

/**
 * The project sidebar (N-101 to N-104): one door to every Agile screen of the open project.
 * It follows the open screen, so it needs no change in the screens themselves.
 */
export class AgileSidebar extends Component {
    static template = "agile_community.Sidebar";
    props = useProps();

    setup() {
        this.orm = useService("orm");
        this.action = usePlugin(ActionPlugin);
        this.dialog = useService("dialog");
        this.state = proxy({ data: null, entry: null, more: false });
        this.token = 0;
        useBus(this.env.bus, "ACTION_MANAGER:UI-UPDATED", () => this.refresh());
        useBus(this.env.bus, "AGILE:SIDEBAR-REFRESH", () => this.refresh());
        onMounted(() => this.refresh());
    }

    async refresh() {
        const target = sidebarTarget(this.action.currentController);
        const token = ++this.token;
        this.state.more = false;
        if (!target) {
            return this.hide();
        }
        let data;
        try {
            data = await this.orm.call("project.project", "agile_sidebar_data", [[target.projectId]]);
        } catch {
            data = { enabled: false };
        }
        if (token !== this.token) {
            return;
        }
        if (!data.enabled) {
            return this.hide();
        }
        this.state.data = data;
        this.state.entry = target.entry;
        document.body.classList.add(BODY_CLASS);
    }

    hide() {
        this.state.data = null;
        document.body.classList.remove(BODY_CLASS);
    }

    get entries() {
        const allowed = new Set(this.state.data?.entries || []);
        return SIDEBAR_ENTRIES.filter((entry) => allowed.has(entry.key));
    }

    get groups() {
        const groups = [];
        for (const entry of this.entries) {
            // Group names are lazy translations, so compare their text.
            const name = String(entry.group);
            const last = groups[groups.length - 1];
            if (last && last.name === name) {
                last.entries.push(entry);
            } else {
                groups.push({ name, entries: [entry] });
            }
        }
        return groups;
    }

    get bottomEntries() {
        return this.entries.filter((entry) => BOTTOM_KEYS.includes(entry.key));
    }

    get moreEntries() {
        return this.entries.filter((entry) => !BOTTOM_KEYS.includes(entry.key));
    }

    /** Badge text for an entry: open backlog size, blocked count on the board. */
    badgeFor(key) {
        const counts = this.state.data?.counts || {};
        if (key === "backlog" && counts.backlog) {
            return { text: String(counts.backlog), danger: false, tip: _t("Issues waiting in the backlog") };
        }
        if (key === "mine" && counts.mine) {
            return { text: String(counts.mine), danger: false, tip: _t("Open issues assigned to you") };
        }
        if (key === "roadmap" && counts.late) {
            return { text: String(counts.late), danger: true, tip: _t("Issues planned to start before something they depend on ends") };
        }
        if (key === "board" && counts.blocked) {
            return { text: String(counts.blocked), danger: true, tip: _t("Blocked issues on this board") };
        }
        return null;
    }

    showShortcuts() {
        openShortcutHelp(this.dialog);
    }

    get installUrl() {
        const path = encodeURIComponent("odoo/agile-my-work");
        return `/scoped_app?app_id=agile_community&path=${path}&app_name=Agile`;
    }

    get canInstall() {
        return !isDisplayStandalone();
    }

    toggleMore() {
        this.state.more = !this.state.more;
    }

    /** A board listed under Board: remember it for this person, then open the Board. */
    async openBoard(boardId) {
        this.state.more = false;
        await this.orm.call("project.project", "agile_board_switch", [[this.state.data.id]], { board_id: boardId || false });
        await this.open("board");
    }

    async open(key) {
        this.state.more = false;
        if (key === "settings") {
            // The Settings entry opens the project form on its Settings tab.
            rememberProjectTab("settings");
        }
        const action = await this.orm.call("project.project", "agile_sidebar_action", [[this.state.data.id], key]);
        if (action.help) {
            // An action returned by a method is not marked up by the client, so the help would show as raw HTML (NU-03).
            action.help = markup(action.help);
        }
        await this.action.doAction(action, { clearBreadcrumbs: true });
    }
}

registry.category("main_components").add("agile_community.sidebar", { Component: AgileSidebar });
