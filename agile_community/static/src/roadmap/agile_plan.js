import { Component, onMounted, onWillUpdateProps, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { downloadText } from "../dashboard/dashboard_export";
import { _t } from "@web/core/l10n/translation";
import { AgilePlanScenario, planDate } from "./agile_plan_scenario";
import { AgilePlanBoard } from "./agile_plan_board";

/**
 * Rows of the plan tree, top to bottom: each item, then (when it is open) its initiatives and epics.
 * Items are open unless their id is in `closed`.
 */
export function planRows(items, closed) {
    const rows = [];
    const walk = (list, depth) => {
        for (const item of list) {
            rows.push({ type: "item", item, depth });
            if (closed.has(item.id)) {
                continue;
            }
            walk(item.children, depth + 1);
            for (const epic of item.epics) {
                rows.push({ type: "epic", epic, item, depth: depth + 1 });
            }
        }
    };
    walk(items, 0);
    return rows;
}

/** The dates of an item in words: a typed date, or the rolled one marked "from epics". */
export function planDates(item) {
    const start = item.start || item.rolled_start;
    const end = item.end || item.rolled_end;
    if (!start && !end) {
        return null;
    }
    return {
        start: start && planDate(start),
        end: end && planDate(end || start),
        fromEpics: (!item.start && !!item.rolled_start) || (!item.end && !!item.rolled_end),
    };
}

const BLANK = { id: null, level: "initiative", name: "", parent_id: false, owner_id: false, date_start: "", date_end: "" };

export class AgilePlan extends Component {
    static template = "agile_community.Plan";
    static components = { AgilePlanScenario, AgilePlanBoard };
    static props = { projects: Array, hideDone: Boolean };

    setup() {
        this.orm = useService("orm");
        this.ui = useService("ui");
        this.state = useState({
            loading: true, error: null, data: null, form: null, notice: null, closed: new Set(), labels: null, scenarios: [], scenario: 0, naming: null, scenarioView: "compare",
        });
        onMounted(() => this.load(this.props));
        onWillUpdateProps((next) => this.load(next));
    }

    async load(props) {
        this.state.loading = true;
        this.state.error = null;
        try {
            this.state.data = await this.orm.call("agile.plan.item", "plan_data", [], {
                project_ids: props.projects, hide_done: props.hideDone,
            });
            await this.loadScenarios(props);
        } catch {
            this.state.data = null;
            this.state.error = _t("The plan did not load. Try again.");
        } finally {
            this.state.loading = false;
        }
    }

    async loadScenarios(props) {
        this.state.scenarios = await this.orm.call("agile.plan.scenario", "scenario_list", [], { project_ids: props.projects });
        if (!this.state.scenarios.some((s) => s.id === this.state.scenario)) {
            this.state.scenario = 0;
        }
    }

    onPickScenario(ev) {
        this.state.scenario = Number(ev.target.value);
    }

    async createScenario() {
        const name = (this.state.naming || "").trim();
        if (!name) {
            this.state.notice = _t("Give the scenario a name.");
            return;
        }
        this.state.naming = null;
        this.state.notice = null;
        try {
            this.state.scenario = await this.orm.call("agile.plan.scenario", "scenario_create", [name], { project_ids: this.props.projects });
        } catch (error) {
            this.state.notice = this.errorText(error, _t("The scenario was not created."));
        }
        await this.load(this.props);
    }

    async reloadAfterApply() {
        await this.load(this.props);
    }

    async downloadCsv() {
        this.state.notice = null;
        try {
            const result = await this.orm.call("agile.plan.item", "plan_csv", [], {
                project_ids: this.props.projects, hide_done: this.props.hideDone, scenario_id: this.state.scenario || false,
            });
            if (!result.count) {
                this.state.notice = _t("Nothing to export: no items match this view.");
                return;
            }
            downloadText(result.filename, result.content);
            this.state.notice = _t("Downloaded %(name)s with %(count)s lines.", { name: result.filename, count: result.count });
        } catch (error) {
            this.state.notice = this.errorText(error, _t("The export failed. Try again."));
        }
    }

    /** Open every item, then hand the page to the browser's print dialog. */
    printLayout() {
        const closed = new Set(this.state.closed);
        this.state.closed.clear();
        window.addEventListener("afterprint", () => {
            this.state.closed = closed;
        }, { once: true });
        setTimeout(() => window.print(), 150);
    }

    async onScenarioDeleted() {
        this.state.scenario = 0;
        await this.load(this.props);
    }

    get rows() {
        return planRows(this.state.data.items, this.state.closed);
    }

    get isEmpty() {
        return !!this.state.data && !this.state.data.items.length;
    }

    get themes() {
        return this.state.data.choices.filter((c) => c.level === "theme");
    }

    get labels() {
        return this.state.data.labels;
    }

    planDate(iso) {
        return planDate(iso);
    }

    label(level) {
        return this.labels[level];
    }

    dates(item) {
        return planDates(item);
    }

    progress(item) {
        return item.total ? _t("Done %(done)s of %(total)s", { done: item.done, total: item.total }) : _t("No issues yet");
    }

    fill(item) {
        return item.total ? Math.round((item.done / item.total) * 100) : 0;
    }

    toggle(item) {
        const closed = this.state.closed;
        closed.has(item.id) ? closed.delete(item.id) : closed.add(item.id);
    }

    isOpen(item) {
        return !this.state.closed.has(item.id);
    }

    hasBody(item) {
        return item.children.length || item.epics.length;
    }

    errorText(error, fallback) {
        return error?.data?.message || fallback;
    }

    async run(call, fallback, done) {
        this.state.notice = null;
        try {
            await call();
            if (done) {
                this.state.notice = done;
            }
        } catch (error) {
            this.state.notice = this.errorText(error, fallback);
        }
        await this.load(this.props);
    }

    openNew(level) {
        this.state.form = { ...BLANK, level };
    }

    openEdit(item) {
        this.state.form = {
            id: item.id, level: item.level, name: item.name, parent_id: item.parent_id || false,
            owner_id: item.owner_id || false, date_start: item.start || "", date_end: item.end || "",
        };
    }

    closeForm() {
        this.state.form = null;
    }

    async save() {
        const form = this.state.form;
        if (!form.name.trim()) {
            this.state.notice = _t("Give the item a name.");
            return;
        }
        const vals = {
            name: form.name, level: form.level, parent_id: form.level === "initiative" ? Number(form.parent_id) || false : false,
            owner_id: Number(form.owner_id) || false, date_start: form.date_start || false, date_end: form.date_end || false,
        };
        const id = form.id;
        this.state.form = null;
        await this.run(() => this.orm.call("agile.plan.item", "plan_save", [vals, id || null]), _t("The item was not saved."), _t("Saved."));
    }

    async remove(item) {
        await this.run(() => this.orm.call("agile.plan.item", "plan_delete", [item.id]), _t("The item was not deleted."), _t("Deleted. Its epics are now unplanned."));
    }

    async assign(epicId, itemId) {
        await this.run(() => this.orm.call("agile.plan.item", "plan_assign", [epicId, itemId || false]), _t("The epic was not moved."));
    }

    async onAssign(item, ev) {
        const epicId = Number(ev.target.value);
        ev.target.value = "";
        if (epicId) {
            await this.assign(epicId, item.id);
        }
    }

    async onPlace(epic, ev) {
        const itemId = Number(ev.target.value);
        ev.target.value = "";
        if (itemId) {
            await this.assign(epic.id, itemId);
        }
    }

    openRename() {
        this.state.labels = { theme: this.labels.theme, initiative: this.labels.initiative };
    }

    async saveRename() {
        const labels = this.state.labels;
        this.state.labels = null;
        await this.run(() => this.orm.call("agile.plan.item", "plan_set_labels", [labels.theme, labels.initiative]), _t("The names were not saved."), _t("Names saved."));
    }
}
