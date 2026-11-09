import { Component, onMounted, onWillUpdateProps, proxy, useProps, t } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

const DAY_MS = 86400000;
/** "3 Nov" for a date written 2026-11-03. */
export function planDate(iso) {
    return new Date(`${iso}T00:00:00Z`).toLocaleDateString(undefined, { day: "numeric", month: "short", timeZone: "UTC" });
}

const day = (iso) => Math.round(Date.parse(`${iso}T00:00:00Z`) / DAY_MS);

/**
 * Bars of the compare timeline as percentages of the span of every date shown. Each row has a live bar and a
 * scenario bar; `later` marks a scenario end after the live end (dashed outline in the view).
 */
export function compareBars(rows) {
    const days = [];
    for (const row of rows) {
        for (const iso of [row.live_start, row.live_end, row.start, row.end]) {
            if (iso) {
                days.push(day(iso));
            }
        }
    }
    if (!days.length) {
        return [];
    }
    const first = Math.min(...days);
    const span = Math.max(Math.max(...days) - first + 1, 1);
    const box = (start, end) => start && end
        ? { left: ((day(start) - first) / span) * 100, width: Math.max(((day(end) - day(start) + 1) / span) * 100, 1.5) }
        : null;
    return rows.map((row) => ({
        row,
        live: box(row.live_start, row.live_end),
        scenario: box(row.start, row.end),
        later: !!row.changed && row.later_days > 0,
    }));
}

/** "2 epics move, 1 later than 30 days" for the summary line. */
export function compareSummary(data) {
    if (!data.moves) {
        return _t("Nothing differs from the live plan.");
    }
    const moves = data.moves === 1 ? _t("1 epic moves") : _t("%(n)s epics move", { n: data.moves });
    return data.late ? `${moves}, ${_t("%(n)s later than 30 days", { n: data.late })}` : moves;
}

/** One scenario of a plan view: its epics against the live plan, edit dates, Apply and Restore. */
export class AgilePlanScenario extends Component {
    static template = "agile_community.PlanScenario";
    props = useProps({ scenarioId: t.number(), onChange: t.function(), onDelete: t.function()});

    setup() {
        this.orm = useService("orm");
        this.state = proxy({ data: null, error: null, notice: null, confirm: false, result: null, suggestion: null });
        onMounted(() => this.load(this.props.scenarioId));
        onWillUpdateProps((next) => this.load(next.scenarioId));
    }

    async load(id) {
        this.state.error = null;
        try {
            this.state.data = await this.orm.call("agile.plan.scenario", "scenario_data", [id]);
        } catch {
            this.state.data = null;
            this.state.error = _t("The scenario did not load. Try again.");
        }
    }

    get bars() {
        return compareBars(this.state.data.rows);
    }

    get summary() {
        return compareSummary(this.state.data);
    }

    planDate(iso) {
        return iso ? planDate(iso) : "";
    }

    errorText(error, fallback) {
        return error?.data?.message || fallback;
    }

    statusText(row) {
        switch (row.status) {
            case "stale":
                return row.changed_by
                    ? _t("Changed after this scenario was made (by %s). Will be skipped.", row.changed_by)
                    : _t("Changed after this scenario was made. Will be skipped.");
            case "forbidden":
                return _t("You do not manage this project. Will be skipped.");
            case "moves":
                return row.later_days > 0 ? _t("%s days later", row.later_days) : _t("%s days earlier", -row.later_days);
            default:
                return "";
        }
    }

    barLabel(bar) {
        const row = bar.row;
        return `${row.key} ${this.planDate(row.start)} to ${this.planDate(row.end)}, live ${this.planDate(row.live_start)} to ${this.planDate(row.live_end)}`;
    }

    async setDates(row, which, ev) {
        const start = which === "start" ? ev.target.value : row.start;
        const end = which === "end" ? ev.target.value : row.end;
        this.state.notice = null;
        try {
            await this.orm.call("agile.plan.scenario", "scenario_set_dates", [this.props.scenarioId, row.epic_id, start, end]);
        } catch (error) {
            this.state.notice = this.errorText(error, _t("The dates were not changed."));
        }
        await this.load(this.props.scenarioId);
    }

    async suggest() {
        this.state.notice = null;
        this.state.suggestion = null;
        try {
            this.state.suggestion = await this.orm.call("agile.plan.scenario", "scenario_suggest", [this.props.scenarioId]);
        } catch (error) {
            this.state.notice = this.errorText(error, _t("Dates could not be suggested."));
        }
        await this.load(this.props.scenarioId);
    }

    async toggleLock(row, ev) {
        this.state.notice = null;
        try {
            await this.orm.call("agile.plan.scenario", "scenario_set_lock", [this.props.scenarioId, row.epic_id, ev.target.checked]);
        } catch (error) {
            this.state.notice = this.errorText(error, _t("The lock was not changed."));
        }
        await this.load(this.props.scenarioId);
    }

    askApply() {
        this.state.confirm = true;
    }

    async apply() {
        this.state.confirm = false;
        this.state.notice = null;
        try {
            const result = await this.orm.call("agile.plan.scenario", "scenario_apply", [this.props.scenarioId]);
            this.state.result = result;
            this.state.notice = _t("Applied %s epics.", result.applied.length);
        } catch (error) {
            this.state.notice = this.errorText(error, _t("The scenario was not applied."));
        }
        await this.load(this.props.scenarioId);
        this.props.onChange();
    }

    async restore() {
        this.state.notice = null;
        try {
            const result = await this.orm.call("agile.plan.scenario", "scenario_restore", [this.props.scenarioId]);
            this.state.result = null;
            this.state.notice = result.skipped.length
                ? _t("Restored %(n)s epics. Skipped %(k)s: changed again.", { n: result.restored.length, k: result.skipped.length })
                : _t("Previous dates restored.");
        } catch (error) {
            this.state.notice = this.errorText(error, _t("The dates were not restored."));
        }
        await this.load(this.props.scenarioId);
        this.props.onChange();
    }

    async remove() {
        try {
            await this.orm.call("agile.plan.scenario", "scenario_delete", [this.props.scenarioId]);
        } catch (error) {
            this.state.notice = this.errorText(error, _t("The scenario was not deleted."));
            return;
        }
        this.props.onDelete();
    }
}
