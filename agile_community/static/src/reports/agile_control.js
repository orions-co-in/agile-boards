import { Component, onMounted, useEffect, useRef, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { deserializeDate } from "@web/core/l10n/dates";
import { niceMax } from "./agile_cfd";
import { ReportExport, svgPngBlob } from "./report_export";

const CHART = { w: 720, h: 276, left: 48, right: 12, top: 12, bottom: 44 };
const DAY_MS = 86400000;

/**
 * One dot per finished issue (when it was done, how many days it took), the rolling average as a
 * line through them and the overall average as a flat line. Returns the shapes and scales.
 */
export function controlLayout(data) {
    const plotW = CHART.w - CHART.left - CHART.right;
    const plotH = CHART.h - CHART.top - CHART.bottom;
    const start = deserializeDate(data.from).toMillis();
    const span = Math.max((deserializeDate(data.to).toMillis() - start) / DAY_MS, 1);
    const top = niceMax(Math.max(0, data.average, ...data.issues.map((i) => i.days)));
    const x = (date) => CHART.left + (plotW * ((deserializeDate(date).toMillis() - start) / DAY_MS)) / span;
    const y = (value) => CHART.top + plotH - (plotH * value) / top;
    return {
        top, x, y, plotW, plotH, chart: CHART,
        dots: data.issues.map((issue) => ({ issue, cx: x(issue.date), cy: y(issue.days) })),
        rollingLine: data.issues.map((issue) => `${x(issue.date)},${y(issue.rolling)}`).join(" "),
        averageY: y(data.average),
    };
}

/** "12 issues finished, 4.5 days on average, the longest 11 days" or what to do when none did. */
export function controlText(data) {
    if (!data.issues.length) {
        return _t("No issue with a start and a finish in this range.");
    }
    const count = data.issues.length;
    return _t("%(count)s issues finished, %(average)s days on average, the longest %(longest)s days", {
        count,
        average: data.average,
        longest: data.longest,
    });
}

export class AgileControlChart extends Component {
    static template = "agile_community.ControlChart";
    static components = { ReportExport };
    static props = ["projectId"];

    setup() {
        this.orm = useService("orm");
        this.state = useState({ loading: true, error: null, data: null, from: "", to: "", hover: null, table: false });
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

    get exportTitle() {
        return _t("Control chart");
    }

    exportTable() {
        const d = this.state.data;
        return { columns: [_t("Key"), _t("Title"), _t("Finished"), _t("Days"), _t("Average of the last %(window)s", { window: d.window })], rows: d.issues.map((issue) => [issue.key, issue.name, issue.date, issue.days, issue.rolling]) };
    }

    exportPng() {
        return svgPngBlob(this.chartBox.el.querySelector("svg"), this.exportTitle, this.summary);
    }

    get layout() {
        return this.state.data ? controlLayout(this.state.data) : null;
    }

    get summary() {
        return this.state.data ? controlText(this.state.data) : "";
    }

    get hoverIssue() {
        return this.state.hover === null ? null : this.state.data.issues[this.state.hover];
    }

    async load() {
        this.state.loading = true;
        this.state.error = null;
        try {
            const data = await this.orm.call("agile.report", "control_chart", [
                this.props.projectId,
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

    onDate(field, ev) {
        this.state[field] = ev.target.value;
        return this.load();
    }

    toggleTable() {
        this.state.table = !this.state.table;
    }

    /** The dot nearest to the pointer, by distance across the chart. */
    onMove(ev) {
        const dots = this.layout.dots;
        if (!dots.length) {
            return;
        }
        const box = ev.currentTarget.getBoundingClientRect();
        const px = ((ev.clientX - box.left) / box.width) * CHART.w;
        let best = 0;
        dots.forEach((dot, i) => {
            if (Math.abs(dot.cx - px) < Math.abs(dots[best].cx - px)) {
                best = i;
            }
        });
        this.state.hover = best;
    }

    onLeave() {
        this.state.hover = null;
    }
}
