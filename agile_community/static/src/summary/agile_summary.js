import { Component, onMounted, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { Layout } from "@web/search/layout";
import { AgilePulse } from "@agile_community/components/pulse/agile_pulse";
import { AgileAvatar } from "@agile_community/components/kit/agile_kit";
import { ago, barWidth, flowLines } from "./summary_helpers";
import { unitShort, unitWord } from "../estimate_unit";

// Count tiles in reading order: everything open, then what needs attention, then what is missing.
export const SUMMARY_TILES = [
    { metric: "open", label: _t("Open") },
    { metric: "blocked", label: _t("Blocked"), tone: "danger" },
    { metric: "overdue", label: _t("Overdue"), tone: "warning" },
    { metric: "unassigned", label: _t("Unassigned") },
    { metric: "unestimated", label: _t("Unestimated") },
];

// The Summary's tiles in their default order, named for the person arranging them (S-934).
export const TILE_NAMES = {
    pulse: _t("Sprint progress"),
    counts: _t("Counts"),
    status: _t("Status"),
    flow: _t("Created and resolved"),
    load: _t("Workload"),
    types: _t("Types"),
    epics: _t("Epics"),
    release: _t("Next release"),
    activity: _t("Recent activity"),
};
export const DEFAULT_LAYOUT = Object.keys(TILE_NAMES).map((id) => ({ id, hidden: false }));

/** The layout after moving a shown tile earlier or later among the shown ones; hidden tiles keep their place. */
export function moveInLayout(layout, id, delta) {
    const shown = layout.filter((tile) => !tile.hidden).map((tile) => tile.id);
    const from = shown.indexOf(id);
    const to = from + delta;
    if (from < 0 || to < 0 || to >= shown.length) {
        return layout;
    }
    const next = layout.map((tile) => ({ ...tile }));
    const a = next.findIndex((tile) => tile.id === id);
    const b = next.findIndex((tile) => tile.id === shown[to]);
    [next[a], next[b]] = [next[b], next[a]];
    return next;
}

/** The layout after dropping one tile in front of another. */
export function dropInLayout(layout, id, beforeId) {
    if (id === beforeId) {
        return layout;
    }
    const moving = layout.find((tile) => tile.id === id);
    const rest = layout.filter((tile) => tile.id !== id).map((tile) => ({ ...tile }));
    const at = rest.findIndex((tile) => tile.id === beforeId);
    if (!moving || at < 0) {
        return layout;
    }
    rest.splice(at, 0, { ...moving });
    return rest;
}

const STATUS_LABELS = {
    ready: _t("To Do"),
    progress: _t("In Progress"),
    review: _t("Review"),
    done: _t("Done"),
};

/**
 * The project's front page (S-201 to S-204): sprint pulse, counts, status and type mix,
 * created versus resolved, workload, epics, the next release and recent activity.
 * Every tile opens the screen or list it summarises.
 */
export class AgileSummary extends Component {
    static template = "agile_community.Summary";
    static displayName = _t("Summary");
    static components = { Layout, AgilePulse, AgileAvatar };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            loading: true, error: null, data: null, sprintId: 0,
            layout: DEFAULT_LAYOUT, flowDay: null, editing: false, confirmReset: false, saveError: "", notice: "", announce: "",
        });
        this.dragId = null;
        this.lastSave = null;
        this.tiles = SUMMARY_TILES;
        this.statusLabels = STATUS_LABELS;
        this.display = { controlPanel: {} };
        onMounted(() => this.load());
    }

    get projectId() {
        const action = this.props.action || {};
        return action.params?.project_id ?? action.context?.active_id ?? action.context?.default_project_id;
    }

    async load(keepPage = false) {
        this.state.loading = !keepPage;
        this.state.error = null;
        try {
            this.state.data = await this.orm.call("project.project", "agile_summary_data", [[this.projectId]], {
                sprint_id: this.state.sprintId || null,
            });
            if (!this.state.editing) {
                this.state.layout = this.state.data.layout || DEFAULT_LAYOUT;
            }
        } catch (error) {
            this.state.data = null;
            this.state.error = error?.data?.message || error?.message || _t("Could not load the summary.");
        } finally {
            this.state.loading = false;
        }
    }

    // ---- arranging the tiles (S-934): each person's own order, saved as they go ----

    tileName(id) {
        return TILE_NAMES[id] || id;
    }

    get shownTiles() {
        return this.state.layout.filter((tile) => !tile.hidden);
    }

    get hiddenTiles() {
        return this.state.layout.filter((tile) => tile.hidden);
    }

    toggleEdit() {
        this.state.editing = !this.state.editing;
        this.state.confirmReset = false;
    }

    /** Show the new layout at once and save it; a failed save keeps the screen and offers Retry. */
    async applyLayout(layout, message) {
        this.state.layout = layout;
        this.state.announce = message || "";
        await this.saveLayout(layout);
    }

    async saveLayout(layout) {
        this.lastSave = layout;
        try {
            await this.orm.call("project.project", "agile_save_summary_layout", [[this.projectId], layout]);
            this.state.saveError = "";
        } catch (error) {
            this.state.saveError = _t("Could not save your layout.");
        }
    }

    retrySave() {
        return this.saveLayout(this.lastSave ?? this.state.layout);
    }

    moveTile(id, delta) {
        const layout = moveInLayout(this.state.layout, id, delta);
        if (layout === this.state.layout) {
            return;
        }
        const position = layout.filter((tile) => !tile.hidden).findIndex((tile) => tile.id === id) + 1;
        return this.applyLayout(
            layout,
            _t("%(name)s is now %(n)s of %(total)s.", { name: this.tileName(id), n: position, total: this.shownTiles.length })
        );
    }

    hideTile(id) {
        if (this.shownTiles.length <= 1) {
            this.state.announce = _t("Keep at least one tile.");
            this.state.notice = this.state.announce;
            return;
        }
        this.state.notice = "";
        return this.applyLayout(
            this.state.layout.map((tile) => (tile.id === id ? { ...tile, hidden: true } : { ...tile })),
            _t("%(name)s is hidden.", { name: this.tileName(id) })
        );
    }

    showTile(id) {
        const rest = this.state.layout.filter((tile) => tile.id !== id).map((tile) => ({ ...tile }));
        return this.applyLayout([...rest, { id, hidden: false }], _t("%(name)s is shown at the end.", { name: this.tileName(id) }));
    }

    async resetLayout() {
        this.state.confirmReset = false;
        this.state.layout = DEFAULT_LAYOUT;
        this.state.announce = _t("Your Summary is back to the default.");
        this.lastSave = null;
        try {
            await this.orm.call("project.project", "agile_save_summary_layout", [[this.projectId], null]);
            this.state.saveError = "";
        } catch {
            this.state.saveError = _t("Could not save your layout.");
        }
    }

    onBarKey(ev, id) {
        if (!ev.altKey || ev.target !== ev.currentTarget) {
            return;
        }
        const delta = { ArrowUp: -1, ArrowLeft: -1, ArrowDown: 1, ArrowRight: 1 }[ev.key];
        if (delta) {
            ev.preventDefault();
            return this.moveTile(id, delta);
        }
    }

    onDragStart(ev, id) {
        this.dragId = id;
        ev.dataTransfer?.setData("text/plain", id);
    }

    dropOn(id) {
        const layout = dropInLayout(this.state.layout, this.dragId, id);
        this.dragId = null;
        if (layout !== this.state.layout) {
            return this.applyLayout(layout, _t("Tiles rearranged."));
        }
    }

    /** With several active sprints the page can follow one of them; the default is all together. */
    onSprintChange(ev) {
        this.state.sprintId = Number(ev.target.value) || 0;
        return this.load(true);
    }

    onFlowKey(ev) {
        const last = this.flowChart.days.length - 1;
        if (ev.key === "ArrowLeft" || ev.key === "ArrowRight") {
            ev.preventDefault();
            const current = this.state.flowDay ?? (ev.key === "ArrowLeft" ? last + 1 : -1);
            this.state.flowDay = Math.max(0, Math.min(last, current + (ev.key === "ArrowLeft" ? -1 : 1)));
        } else if (ev.key === "Escape") {
            this.state.flowDay = null;
        }
    }

    get flowChart() {
        return flowLines(this.state.data.flow);
    }

    get maxStatus() {
        return Math.max(0, ...this.state.data.status.map((row) => row.count));
    }

    get maxType() {
        return Math.max(0, ...this.state.data.types.map((row) => row.count));
    }

    unitShort = unitShort;
    unitWord = unitWord;

    get maxLoad() {
        const rows = [...this.state.data.workload.people, this.state.data.workload.unassigned];
        return Math.max(0, ...rows.map((row) => row.issues));
    }

    width(value, max) {
        return barWidth(value, max);
    }

    when(isoDateTime) {
        return ago(isoDateTime);
    }

    /** Run a project button method the way a form button would, so the action completes properly. */
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

    openBoard() {
        return this.callButton("action_view_tasks");
    }

    openBacklog() {
        return this.callButton("action_open_agile_backlog");
    }

    openRoadmap() {
        return this.callButton("action_open_agile_roadmap_page");
    }

    openReports() {
        return this.callButton("action_open_agile_reports");
    }

    openRecord(resModel, resId) {
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: resModel,
            res_id: resId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openSprint(sprintId) {
        return this.openRecord("project.sprint", sprintId);
    }

    planSprint() {
        return this.callButton("action_sprints");
    }
}

registry.category("actions").add("agile_community.summary", AgileSummary);
