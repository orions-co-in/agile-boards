import { Component, onMounted, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { Layout } from "@web/search/layout";
import { AgilePulse } from "@agile_community/components/pulse/agile_pulse";

// Tile order is the reading order: everything open, then what needs attention.
export const OVERVIEW_TILES = [
    { metric: "open", label: _t("Open issues") },
    { metric: "blocked", label: _t("Blocked"), tone: "danger" },
    { metric: "overdue", label: _t("Overdue"), tone: "warning" },
    { metric: "review", label: _t("In review") },
];

export class AgileOverview extends Component {
    static template = "agile_community.Overview";
    // Breadcrumb label when the action is restored from the URL.
    static displayName = _t("Overview");
    static components = { Layout, AgilePulse };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ loading: true, error: null, data: null });
        this.tiles = OVERVIEW_TILES;
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
            this.state.data = await this.orm.call("project.project", "agile_pulse_data", [[this.projectId]]);
        } catch (error) {
            this.state.data = null;
            this.state.error = error?.data?.message || error?.message || _t("Could not load the sprint pulse.");
        } finally {
            this.state.loading = false;
        }
    }

    /**
     * Run a project button method the way a form button would, so the server
     * action is completed (views, breadcrumbs) exactly like the Agile Overview tab.
     */
    async callButton(method, context = {}) {
        await this.action.doActionButton({
            type: "object",
            name: method,
            resModel: "project.project",
            resId: this.projectId,
            context,
        });
    }

    openTile(metric) {
        return this.callButton("action_view_agile_metric_issues", { agile_metric_filter: metric });
    }

    openReports() {
        return this.callButton("action_view_agile_reports");
    }

    async openSprint(sprintId) {
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "project.sprint",
            res_id: sprintId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    planSprint() {
        return this.callButton("action_sprints");
    }
}

registry.category("actions").add("agile_community.overview", AgileOverview);
