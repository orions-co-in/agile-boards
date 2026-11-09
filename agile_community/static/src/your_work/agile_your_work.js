import { Component, onMounted, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { Layout } from "@web/search/layout";
import { AgileLozenge } from "@agile_community/components/kit/agile_kit";

// The four tabs of the top-menu My Work, limited to one project (D-805).
export const YOUR_WORK_TABS = [
    { key: "assigned", label: _t("Assigned") },
    { key: "review", label: _t("Review requested") },
    { key: "blocked", label: _t("Blocked") },
    { key: "due", label: _t("Due soon") },
];

const STATUS_LABELS = {
    backlog: _t("Backlog"),
    ready: _t("To Do"),
    progress: _t("In Progress"),
    review: _t("Review"),
    done: _t("Done"),
    canceled: _t("Canceled"),
};

const EMPTY_TEXT = {
    assigned: _t("No open issues are assigned to you in this project."),
    review: _t("Nothing is waiting for review."),
    blocked: _t("None of your open issues are blocked."),
    due: _t("You have nothing due in the next seven days."),
};

/** The person's own work in this project, in four tabs with counts. */
export class AgileYourWork extends Component {
    static template = "agile_community.YourWork";
    static displayName = _t("Your work");
    static components = { Layout, AgileLozenge };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ loading: true, error: null, data: null, tab: "assigned" });
        this.tabs = YOUR_WORK_TABS;
        this.display = { controlPanel: {} };
        onMounted(() => this.load());
    }

    get projectId() {
        const action = this.props.action || {};
        return action.params?.project_id ?? action.context?.active_id ?? action.context?.default_project_id;
    }

    async load() {
        this.state.loading = true;
        this.state.error = null;
        try {
            this.state.data = await this.orm.call("project.project", "agile_your_work_data", [[this.projectId]]);
        } catch (error) {
            this.state.data = null;
            this.state.error = error?.data?.message || error?.message || _t("Could not load your work.");
        } finally {
            this.state.loading = false;
        }
    }

    get current() {
        return this.state.data.tabs[this.state.tab];
    }

    get emptyText() {
        return EMPTY_TEXT[this.state.tab];
    }

    statusLabel(status) {
        return STATUS_LABELS[status] || "";
    }

    pickTab(key) {
        this.state.tab = key;
    }

    /** Arrow keys move between tabs, as a tab list should. */
    onTabKey(ev) {
        const keys = this.tabs.map((tab) => tab.key);
        const index = keys.indexOf(this.state.tab);
        const step = ev.key === "ArrowRight" ? 1 : ev.key === "ArrowLeft" ? -1 : 0;
        if (step) {
            ev.preventDefault();
            this.state.tab = keys[(index + step + keys.length) % keys.length];
        }
    }

    openIssue(id) {
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "project.task",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openAllProjects() {
        return this.action.doAction("agile_community.action_agile_my_work_assigned");
    }
}

registry.category("actions").add("agile_community.your_work", AgileYourWork);
