import { Component, proxy, useProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/** The tabs of the History panel, in order; "all" shows every entry. */
export function historyTabs() {
    return [
        { key: "all", label: _t("All") },
        { key: "comment", label: _t("Comments") },
        { key: "history", label: _t("History") },
        { key: "worklog", label: _t("Work log") },
    ];
}

/**
 * The History panel (S-1128): comments, field changes and logged work of an issue, one tab each.
 * It reads the feed once; switching tabs only filters it.
 */
export class AgileHistory extends Component {
    static template = "agile_community.History";
    props = useProps({ ...standardFieldProps });

    setup() {
        this.orm = useService("orm");
        this.state = proxy({ loading: true, error: null, data: null, tab: "all" });
        this.loadedFor = null;
        this.ensureLoaded();
    }

    get resId() {
        return this.props.record.resId;
    }

    get tabs() {
        const entries = this.state.data?.entries || [];
        return historyTabs().map((tab) => ({
            ...tab,
            count: tab.key === "all" ? entries.length : entries.filter((entry) => entry.kind === tab.key).length,
        }));
    }

    get entries() {
        const entries = this.state.data?.entries || [];
        return this.state.tab === "all" ? entries : entries.filter((entry) => entry.kind === this.state.tab);
    }

    get emptyText() {
        switch (this.state.tab) {
            case "comment":
                return _t("No comments yet. Add one in the chatter below.");
            case "history":
                return _t("Nothing has changed on this issue yet.");
            case "worklog":
                return this.state.data.worklog_available
                    ? _t("No work logged yet.")
                    : _t("Work log needs the Timesheets app. Install it to log time on issues.");
            default:
                return _t("No activity yet.");
        }
    }

    async ensureLoaded() {
        if (!this.resId || this.loadedFor === this.resId) {
            this.state.loading = false;
            return;
        }
        this.loadedFor = this.resId;
        this.state.loading = true;
        this.state.error = null;
        try {
            this.state.data = await this.orm.call("project.task", "agile_history_feed", [[this.resId]]);
        } catch {
            this.state.error = _t("The history did not load. Try again.");
        }
        this.state.loading = false;
    }

    retry() {
        this.loadedFor = null;
        return this.ensureLoaded();
    }

    async selectTab(key) {
        this.state.tab = key;
        // Anything added in the chatter since the panel loaded appears now, without a loading flash.
        try {
            this.state.data = await this.orm.call("project.task", "agile_history_feed", [[this.resId]]);
        } catch {
            // The entries already shown stay.
        }
    }

    /** Arrow keys move between tabs, as people expect from a tab list. */
    onTabKey(ev) {
        const keys = historyTabs().map((tab) => tab.key);
        const at = keys.indexOf(this.state.tab);
        let next = null;
        if (ev.key === "ArrowRight") {
            next = keys[(at + 1) % keys.length];
        } else if (ev.key === "ArrowLeft") {
            next = keys[(at - 1 + keys.length) % keys.length];
        }
        if (next) {
            ev.preventDefault();
            this.state.tab = next;
            ev.currentTarget.parentElement.querySelector(`[data-tab="${next}"]`)?.focus();
        }
    }

    hoursText(hours) {
        const rounded = Math.round(hours * 100) / 100;
        return _t("%(hours)s h", { hours: rounded });
    }
}

registry.category("fields").add("agile_history", {
    component: AgileHistory,
    supportedTypes: ["one2many"],
});
