import { Component, onMounted, useEffect, useRef, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { niceMax } from "./agile_cfd";
import { ReportExport, svgPngBlob } from "./report_export";
import { unitWord } from "../estimate_unit";

const CHART = { w: 720, h: 276, left: 48, right: 12, top: 12, bottom: 44 };

/**
 * Remaining points as an area and the scope (total points) as a stepped line, so work added to
 * the epic or release shows as a step up. Returns the drawn shapes and the scale functions.
 */
export function burndownLayout(days) {
    const plotW = CHART.w - CHART.left - CHART.right;
    const plotH = CHART.h - CHART.top - CHART.bottom;
    const top = niceMax(Math.max(0, ...days.map((d) => d.scope)));
    const x = (i) => CHART.left + (days.length < 2 ? plotW / 2 : (plotW * i) / (days.length - 1));
    const y = (value) => CHART.top + plotH - (plotH * value) / top;
    const remaining = days.map((d, i) => `${x(i)},${y(d.remaining)}`);
    const area = [...remaining, `${x(days.length - 1)},${y(0)}`, `${x(0)},${y(0)}`].join(" ");
    // Stepped: the scope holds until the day it changes.
    const steps = [];
    days.forEach((d, i) => {
        if (i) {
            steps.push(`${x(i)},${y(days[i - 1].scope)}`);
        }
        steps.push(`${x(i)},${y(d.scope)}`);
    });
    return { top, x, y, plotH, plotW, chart: CHART, remainingLine: remaining.join(" "), area, scopeLine: steps.join(" ") };
}

/** "8 of 21 points left" and what that leaves out. */
export function leftText(day, unestimated, unit) {
    const base = _t("%(left)s of %(scope)s %(unit)s left", { left: day.remaining, scope: day.scope, unit: unitWord(unit) });
    return unestimated ? `${base}. ${_t("%(count)s issues have no estimate yet.", { count: unestimated })}` : base;
}

export class AgileBurndown extends Component {
    unitWord = unitWord;

    static template = "agile_community.Burndown";
    static components = { ReportExport };
    static props = ["projectId", "kind", "targets", "onOpen", "initialTargetId?"];

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            loading: false,
            error: null,
            data: null,
            targetId: this.props.initialTargetId ?? this.props.targets[0]?.id ?? null,
            from: "",
            to: "",
            hover: null,
            table: false,
        });
        // On a phone the chart is wider than the screen; start at its right end, where today is.
        this.chartBox = useRef("chartBox");
        useEffect(
            (box) => {
                if (box) {
                    box.scrollLeft = box.scrollWidth;
                }
            },
            () => [this.chartBox.el, this.state.data]
        );
        onMounted(() => this.load());
    }

    get noun() {
        return this.props.kind === "epic" ? _t("epic") : _t("release");
    }

    get title() {
        const target = this.props.targets.find((t) => t.id === this.state.targetId);
        return target
            ? _t("How much of %(name)s is left?", { name: target.name })
            : _t("How much of this %(noun)s is left?", { noun: this.noun });
    }

    get exportTitle() {
        return `${this.noun} burndown ${this.props.targets.find((t) => t.id === this.state.targetId)?.name || ""}`.trim();
    }

    exportTable() {
        const d = this.state.data;
        return { columns: [_t("Day"), _t("Left"), _t("Done"), _t("Scope"), _t("Issues")], rows: d.days.map((day) => [day.date, day.remaining, day.done, day.scope, day.issues]) };
    }

    exportPng() {
        return svgPngBlob(this.chartBox.el.querySelector("svg"), this.exportTitle, this.title);
    }

    get layout() {
        return this.state.data?.days.length ? burndownLayout(this.state.data.days) : null;
    }

    get hoverDay() {
        return this.state.hover === null ? null : this.state.data.days[this.state.hover];
    }

    get summary() {
        const days = this.state.data?.days || [];
        return days.length ? leftText(days[days.length - 1], this.state.data.unestimated, this.state.data.estimate_unit) : "";
    }

    /** Record today's figures now (managers only; the server says so otherwise), then draw again. */
    async recordNow() {
        try {
            await this.orm.call("agile.report", "record_history_now", [this.props.projectId]);
        } catch (error) {
            this.state.error = error?.data?.message || error?.message || String(error);
            return;
        }
        await this.load();
    }

    async load() {
        if (this.state.targetId === null) {
            return;
        }
        this.state.loading = true;
        this.state.error = null;
        try {
            const data = await this.orm.call("agile.report", "burndown", [
                this.props.projectId,
                this.props.kind,
                this.state.targetId,
                this.state.from || false,
                this.state.to || false,
            ]);
            this.state.data = data;
            this.state.from = data.from;
            this.state.to = data.to;
        } catch (error) {
            this.state.error = error?.data?.message || error?.message || _t("The report could not load. Try again.");
        } finally {
            this.state.loading = false;
        }
    }

    onTarget(ev) {
        this.state.targetId = parseInt(ev.target.value, 10);
        return this.load();
    }

    onDate(field, ev) {
        this.state[field] = ev.target.value;
        return this.load();
    }

    toggleTable() {
        this.state.table = !this.state.table;
    }

    indexAt(ev) {
        const box = ev.currentTarget.getBoundingClientRect();
        const px = ((ev.clientX - box.left) / box.width) * CHART.w;
        const days = this.state.data.days;
        const step = days.length < 2 ? 1 : this.layout.plotW / (days.length - 1);
        return Math.max(0, Math.min(days.length - 1, Math.round((px - CHART.left) / step)));
    }

    onMove(ev) {
        this.state.hover = this.indexAt(ev);
    }

    onLeave() {
        this.state.hover = null;
    }

    onChartClick(ev) {
        this.open(this.state.data.days[this.indexAt(ev)].date);
    }

    open(date) {
        return this.props.onOpen("burndown_issues", [this.props.projectId, this.props.kind, this.state.targetId, date]);
    }
}
