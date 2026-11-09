import { Component, markup, onMounted, proxy, usePlugin, useProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { browser } from "@web/core/browser/browser";
import { Layout } from "@web/search/layout";
import { AgileCfd } from "./agile_cfd";
import { AgileBurndown } from "./agile_burndown";
import { AgileBurnup } from "./agile_burnup";
import { AgileControlChart } from "./agile_control";
import { AgileDeploys } from "./agile_deploys";
import { ReportExport, sprintPngBlob } from "./report_export";
import { unitShort, unitWord } from "../estimate_unit";
import { ActionPlugin } from "@web/webclient/actions/action_plugin";

// The four numbers of the sprint report, in the order a person reads them.
export const SPRINT_TILES = [
    { code: "completed", label: _t("Completed") },
    { code: "carried", label: _t("Carried over"), openLabel: _t("Still open") },
    { code: "added", label: _t("Added during the sprint") },
    { code: "removed", label: _t("Removed from the sprint") },
];

/** "Delivered 21 of 24 planned points, 88%" or what to do when there was no plan. */
export function deliveredText(delivered, soFar, unit) {
    if (!delivered.planned_points) {
        return _t("No %(unit)s were planned at the start.", { unit: unitWord(unit) });
    }
    const verb = soFar ? _t("Delivered so far") : _t("Delivered");
    return _t("%(verb)s %(done)s of %(planned)s planned %(unit)s, %(percent)s%", {
        verb,
        unit: unitWord(unit),
        done: delivered.completed_points,
        planned: delivered.planned_points,
        percent: delivered.percent,
    });
}

/** "3 issues, 8 points" (and what the person cannot see, if anything). */
export function groupText(group, unit) {
    const issues = group.count === 1 ? _t("1 issue") : _t("%(count)s issues", { count: group.count });
    const points = _t("%(points)s %(unit)s", { points: group.points, unit: unitWord(unit) });
    const hidden = group.hidden ? _t(" (%(hidden)s you cannot see)", { hidden: group.hidden }) : "";
    return `${issues}, ${points}${hidden}`;
}

/** An action built on the server carries its empty-state help as plain text; the web client needs it as markup (NU-33). */
export function withMarkedHelp(action) {
    return action && typeof action.help === "string" ? { ...action, help: markup(action.help) } : action;
}

export class AgileReports extends Component {
    static template = "agile_community.Reports";
    static displayName = _t("Reports");
    static components = { Layout, AgileCfd, AgileBurndown, AgileBurnup, AgileControlChart, AgileDeploys, ReportExport };
    props = useProps();

    setup() {
        this.orm = useService("orm");
        this.action = usePlugin(ActionPlugin);
        this.state = proxy({
            loading: true,
            error: null,
            meta: null,
            report: "sprint",
            sprintId: null,
            data: null,
            actionName: "",
        });
        this.display = { controlPanel: {} };
        onMounted(() => this.start());
    }

    /** The picker's reports grouped under their headings, in the order the server lists them. */
    get pickerGroups() {
        const groups = [];
        for (const report of this.state.meta?.reports || []) {
            let group = groups.find((g) => g.name === report.group);
            if (!group) {
                group = { name: report.group, reports: [] };
                groups.push(group);
            }
            group.reports.push(report);
        }
        return groups;
    }

    pick(code) {
        const report = this.state.meta?.reports.find((entry) => entry.code === code);
        if (report?.native) {
            return this.openNative(code);
        }
        this.state.report = code;
        this.remember(code);
    }

    onSwitch(ev) {
        const code = ev.target.value;
        this.pick(code);
        // A native report leaves this screen; put the choice back until it is really open.
        ev.target.value = this.state.report;
    }

    /** The last report seen in this browser, per project, so the hub reopens where the person left. */
    get memoryKey() {
        return `agile_reports_last_${this.projectId}`;
    }

    remember(code) {
        try {
            browser.localStorage.setItem(this.memoryKey, code);
        } catch {
            // Private windows can refuse storage; the hub then opens on the sprint report.
        }
    }

    recall() {
        try {
            const code = browser.localStorage.getItem(this.memoryKey);
            const known = this.state.meta.reports.find((entry) => entry.code === code && !entry.native);
            return known ? code : this.firstReport();
        } catch {
            return this.firstReport();
        }
    }

    /** A Kanban project has no sprint report, so the hub opens on the first report it does have (NU-49). */
    firstReport() {
        return this.state.meta.reports.find((entry) => !entry.native)?.code || "sprint";
    }

    /** The existing delivery screens (burndown, velocity, ...) open as their own list or chart. */
    async openNative(code) {
        const action = await this.orm.call("agile.report", "native_report_action", [this.projectId, code]);
        await this.action.doAction(withMarkedHelp(action));
    }

    /** Run a report's drill-down on the server and open the list it returns. */
    async drill(method, args) {
        const action = await this.orm.call("agile.report", method, args);
        await this.action.doAction(withMarkedHelp(action));
    }

    get projectId() {
        const action = this.props.action || {};
        return action.params?.project_id ?? action.context?.active_id ?? action.context?.default_project_id;
    }

    get sprint() {
        return this.state.meta?.sprints.find((sprint) => sprint.id === this.state.sprintId);
    }

    /** A planned sprint has delivered and changed nothing yet; only its plan is worth showing (NU-52). */
    get notStarted() {
        return this.sprint?.state === "draft";
    }

    get tiles() {
        return this.notStarted
            ? [{ code: "carried", label: _t("Planned so far"), openLabel: _t("Planned so far") }]
            : SPRINT_TILES;
    }

    get question() {
        const name = this.sprint?.name || "";
        if (this.notStarted) {
            return _t("What is planned for %(sprint)s?", { sprint: name });
        }
        return this.state.data?.so_far
            ? _t("How is %(sprint)s going?", { sprint: name })
            : _t("What did %(sprint)s deliver?", { sprint: name });
    }

    unitShort = unitShort;

    get delivered() {
        if (this.notStarted) {
            return _t("%(sprint)s has not started yet.", { sprint: this.sprint.name });
        }
        return deliveredText(this.state.data.delivered, this.state.data.so_far, this.state.data.estimate_unit);
    }

    groupText(code) {
        return groupText(this.state.data.groups[code], this.state.data.estimate_unit);
    }

    /** Width of the delivered bar against the planned bar, never past the full width. */
    get barWidths() {
        const d = this.state.data.delivered;
        const top = Math.max(d.planned_points, d.completed_points) || 1;
        return {
            planned: Math.round((100 * d.planned_points) / top),
            delivered: Math.round((100 * d.completed_points) / top),
        };
    }

    get exportTitle() {
        return _t("%(sprint)s report", { sprint: this.sprint?.name || "" });
    }

    /** One line per issue of the four groups, as on screen (what the person cannot see is not in the data). */
    exportTable() {
        const data = this.state.data;
        const rows = [];
        for (const tile of this.tiles) {
            const label = tile.code === "carried" && data.so_far ? tile.openLabel : tile.label;
            for (const issue of data.groups[tile.code].issues) {
                rows.push([label, issue.key, issue.name, issue.status, issue.points, issue.where || ""]);
            }
        }
        return { columns: [_t("Group"), _t("Key"), _t("Title"), _t("Status"), _t("Estimate"), _t("Where it went")], rows };
    }

    exportPng() {
        const data = this.state.data;
        const unit = unitShort(data.estimate_unit);
        const widths = this.barWidths;
        const bars = [
            { label: _t("Planned"), percent: widths.planned, text: `${data.delivered.planned_points} ${unit}` },
            { label: _t("Delivered"), percent: widths.delivered, text: `${data.delivered.completed_points} ${unit}` },
        ];
        const counts = this.tiles.map((tile) => ({
            count: data.groups[tile.code].count,
            label: tile.code === "carried" && data.so_far ? tile.openLabel : tile.label,
            text: this.groupText(tile.code),
        }));
        return sprintPngBlob(this.exportTitle, this.delivered, bars, counts);
    }

    async start() {
        if (!this.projectId) {
            this.state.loading = false;
            this.state.error = _t("Open the reports from a project.");
            return;
        }
        try {
            this.state.meta = await this.orm.call("agile.report", "reports_meta", [this.projectId]);
            const first = this.state.meta.sprints.find((s) => s.state !== "draft") || this.state.meta.sprints[0];
            this.state.sprintId = first?.id ?? null;
            this.state.report = this.recall();
            this.applyDeepLink();
        } catch (error) {
            this.fail(error);
            return;
        }
        await this.load();
    }

    /** Opened from a sprint, epic or release: show that report for that record, not the remembered one. */
    applyDeepLink() {
        const params = this.props.action?.params || {};
        const meta = this.state.meta;
        if (params.report === "sprint" && meta.sprints.some((sprint) => sprint.id === params.sprint_id)) {
            this.state.report = "sprint";
            this.state.sprintId = params.sprint_id;
        } else if (params.report === "epic" || params.report === "release") {
            const targets = params.report === "epic" ? meta.epics : meta.releases;
            if (targets.some((target) => target.id === params.target_id)) {
                this.state.report = params.report;
                this.initialTargetId = params.target_id;
            }
        }
    }

    fail(error) {
        this.state.loading = false;
        this.state.error = error?.data?.message || error?.message || _t("The report could not load. Try again.");
    }

    async load() {
        this.state.error = null;
        if (!this.state.meta) {
            return this.start();
        }
        if (!this.state.sprintId) {
            this.state.loading = false;
            this.state.data = null;
            return;
        }
        this.state.loading = true;
        try {
            this.state.data = await this.orm.call("agile.report", "sprint_report", [
                this.projectId,
                this.state.sprintId,
            ]);
            this.state.loading = false;
        } catch (error) {
            this.fail(error);
        }
    }

    onSprint(ev) {
        this.state.sprintId = parseInt(ev.target.value, 10);
        return this.load();
    }

    async openGroup(code) {
        const action = await this.orm.call("agile.report", "sprint_report_issues", [
            this.projectId,
            this.state.sprintId,
            code,
        ]);
        await this.action.doAction(action);
    }

    async addRetroAction(ev) {
        ev.preventDefault();
        const name = this.state.actionName.trim();
        if (!name) {
            return;
        }
        await this.orm.call("project.sprint", "agile_retro_add_action", [[this.state.sprintId], name]);
        this.state.actionName = "";
        await this.load();
    }

    openIssue(issue) {
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "project.task",
            res_id: issue.id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openMoreReports() {
        return this.action.doActionButton({
            type: "object",
            name: "action_view_agile_reports",
            resModel: "project.project",
            resId: this.projectId,
            context: {},
        });
    }
}

registry.category("actions").add("agile_community.reports", AgileReports);
