import { signal } from "@odoo/owl";
import { Component, onMounted, proxy, useProps, t } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { niceMax } from "./agile_cfd";
import { ReportExport, svgPngBlob } from "./report_export";
import { unitWord } from "../estimate_unit";
import {useLayoutEffect} from "@web/owl2/utils";

const CHART = { w: 720, h: 276, left: 48, right: 12, top: 12, bottom: 44 };

/**
 * Done as an area and the sprint scope as a stepped line: when the scope line steps up, work was
 * added; the gap between the lines is what is left. Returns the shapes and the scale functions.
 */
export function burnupLayout(days) {
    const plotW = CHART.w - CHART.left - CHART.right;
    const plotH = CHART.h - CHART.top - CHART.bottom;
    const top = niceMax(Math.max(0, ...days.map((d) => d.scope)));
    const x = (i) => CHART.left + (days.length < 2 ? plotW / 2 : (plotW * i) / (days.length - 1));
    const y = (value) => CHART.top + plotH - (plotH * value) / top;
    const done = days.map((d, i) => `${x(i)},${y(d.done)}`);
    const area = [...done, `${x(days.length - 1)},${y(0)}`, `${x(0)},${y(0)}`].join(" ");
    const steps = [];
    days.forEach((d, i) => {
        if (i) {
            steps.push(`${x(i)},${y(days[i - 1].scope)}`);
        }
        steps.push(`${x(i)},${y(d.scope)}`);
    });
    if (days.length === 1) {
        // One day has no line to draw, so the scope shows as a short bar through its point.
        steps.unshift(`${x(0) - 24},${y(days[0].scope)}`);
        steps.push(`${x(0) + 24},${y(days[0].scope)}`);
    }
    return { top, x, y, plotH, plotW, chart: CHART, doneLine: done.join(" "), area, scopeLine: steps.join(" ") };
}

/** "13 of 21 points done" and, when it grew, by how much the scope changed. */
export function doneText(days, unit) {
    const last = days[days.length - 1];
    const base = _t("%(done)s of %(scope)s %(unit)s done", { done: last.done, scope: last.scope, unit: unitWord(unit) });
    const grew = last.scope - days[0].scope;
    if (!grew) {
        return base;
    }
    const change = grew > 0
        ? _t("The scope grew by %(n)s since %(date)s.", { n: grew, date: days[0].date })
        : _t("The scope shrank by %(n)s since %(date)s.", { n: -grew, date: days[0].date });
    return `${base}. ${change}`;
}

export class AgileBurnup extends Component {
    static template = "agile_community.Burnup";
    static components = { ReportExport };
    props = useProps({projectId: t.any(), sprints: t.any(), initialSprintId: t.any().optional()});

    setup() {
        this.orm = useService("orm");
        this.unitWord = unitWord;
        this.state = proxy({
            loading: false,
            error: null,
            data: null,
            sprintId: this.props.initialSprintId ?? this.props.sprints[0]?.id ?? null,
            hover: null,
            table: false,
        });
        this.chartBox = signal.ref();
        useLayoutEffect(
            (box) => {
                if (box) {
                    box.scrollLeft = box.scrollWidth;
                }
            },
            () => [this.chartBox(), this.state.data]
        );
        onMounted(() => this.load());
    }

    get exportTitle() {
        return `${this.props.sprints.find((s) => s.id === this.state.sprintId)?.name || ""} burnup`.trim();
    }

    exportTable() {
        const d = this.state.data;
        return { columns: [_t("Day"), _t("Done"), _t("Scope"), _t("Left")], rows: d.days.map((day) => [day.date, day.done, day.scope, day.remaining]) };
    }

    exportPng() {
        return svgPngBlob(this.chartBox().querySelector("svg"), this.exportTitle, this.summary);
    }

    get layout() {
        return this.state.data?.days.length ? burnupLayout(this.state.data.days) : null;
    }

    get hoverDay() {
        return this.state.hover === null ? null : this.state.data.days[this.state.hover];
    }

    get summary() {
        const days = this.state.data?.days || [];
        return days.length ? doneText(days, this.state.data.estimate_unit) : "";
    }

    async load() {
        if (this.state.sprintId === null) {
            return;
        }
        this.state.loading = true;
        this.state.error = null;
        try {
            this.state.data = await this.orm.call("agile.report", "burnup", [this.props.projectId, this.state.sprintId]);
        } catch (error) {
            this.state.error = error?.data?.message || error?.message || _t("The report could not load. Try again.");
        } finally {
            this.state.loading = false;
        }
    }

    onSprint(ev) {
        this.state.sprintId = parseInt(ev.target.value, 10);
        this.state.hover = null;
        return this.load();
    }

    toggleTable() {
        this.state.table = !this.state.table;
    }

    onMove(ev) {
        const box = ev.currentTarget.getBoundingClientRect();
        const px = ((ev.clientX - box.left) / box.width) * CHART.w;
        const days = this.state.data.days;
        const step = days.length < 2 ? 1 : this.layout.plotW / (days.length - 1);
        this.state.hover = Math.max(0, Math.min(days.length - 1, Math.round((px - CHART.left) / step)));
    }

    onLeave() {
        this.state.hover = null;
    }
}
