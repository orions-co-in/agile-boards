import { signal } from "@odoo/owl";
import { Component, onMounted, proxy, useProps, t } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { ReportExport, svgPngBlob } from "./report_export";
import {useLayoutEffect} from "@web/owl2/utils";

const CHART = { w: 720, h: 276, left: 48, right: 12, top: 12, bottom: 44 };

/** A pleasant top for the vertical axis: 1, 2, 5 times a power of ten. */
export function niceMax(value) {
    if (value <= 0) {
        return 1;
    }
    const power = 10 ** Math.floor(Math.log10(value));
    const step = [1, 2, 5, 10].find((m) => m * power >= value);
    return step * power;
}

/**
 * Stacked bands, first status at the bottom. Returns one polygon per status plus the day
 * columns used for hover and click.
 */
export function stackLayout(days, statuses) {
    const plotW = CHART.w - CHART.left - CHART.right;
    const plotH = CHART.h - CHART.top - CHART.bottom;
    const top = niceMax(Math.max(0, ...days.map((d) => d.total)));
    const x = (i) => CHART.left + (days.length < 2 ? plotW / 2 : (plotW * i) / (days.length - 1));
    const y = (value) => CHART.top + plotH - (plotH * value) / top;
    const below = days.map(() => 0);
    const bands = statuses.map((status) => {
        const lower = [...below];
        days.forEach((d, i) => (below[i] += d.counts[status.code] || 0));
        const upper = [...below];
        const edge = days.length < 2 ? 4 : 0; // a single day is drawn as a short block
        const points = [
            ...days.map((_d, i) => `${x(i) - edge},${y(upper[i])}`),
            ...days.map((_d, i) => `${x(i) + edge},${y(lower[i])}`).reverse(),
        ];
        return { ...status, points: points.join(" "), lower, upper };
    });
    return { bands, top, x, y, plotH, plotW, chart: CHART };
}

export class AgileCfd extends Component {
    static template = "agile_community.Cfd";
    static components = { ReportExport };
    props = useProps({projectId: t.any(), onOpen: t.any()});

    setup() {
        this.orm = useService("orm");
        this.state = proxy({
            loading: true,
            error: null,
            data: null,
            from: "",
            to: "",
            hover: null,
            table: false,
        });
        // On a phone the chart is wider than the screen; start at its right end, where today is.
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
        return _t("Cumulative flow");
    }

    exportTable() {
        const d = this.state.data;
        return { columns: [_t("Day"), ...d.statuses.map((s) => s.label), _t("Total")], rows: d.days.map((day) => [day.date, ...d.statuses.map((s) => day.counts[s.code] || 0), day.total]) };
    }

    exportPng() {
        return svgPngBlob(this.chartBox().querySelector("svg"), this.exportTitle, `${this.state.data.from} - ${this.state.data.to}`);
    }

    get layout() {
        return this.state.data?.days.length ? stackLayout(this.state.data.days, this.state.data.statuses) : null;
    }

    get hoverDay() {
        return this.state.hover === null ? null : this.state.data.days[this.state.hover];
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
        this.state.loading = true;
        this.state.error = null;
        try {
            const data = await this.orm.call("agile.report", "cfd", [
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

    async lastDays(count) {
        const end = new Date(this.state.to || Date.now());
        const start = new Date(end);
        start.setDate(end.getDate() - count + 1);
        this.state.from = start.toISOString().slice(0, 10);
        this.state.to = end.toISOString().slice(0, 10);
        await this.load();
    }

    toggleTable() {
        this.state.table = !this.state.table;
    }

    /** Which column and band a pointer is over, in chart units. */
    locate(ev) {
        const layout = this.layout;
        const box = ev.currentTarget.getBoundingClientRect();
        const px = ((ev.clientX - box.left) / box.width) * CHART.w;
        const py = ((ev.clientY - box.top) / box.height) * CHART.h;
        const days = this.state.data.days;
        const step = days.length < 2 ? 1 : layout.plotW / (days.length - 1);
        const index = Math.max(0, Math.min(days.length - 1, Math.round((px - CHART.left) / step)));
        const value = ((CHART.top + layout.plotH - py) / layout.plotH) * layout.top;
        const band = layout.bands.find((b) => value >= b.lower[index] && value <= b.upper[index]);
        return { index, status: band?.code };
    }

    onMove(ev) {
        this.state.hover = this.locate(ev).index;
    }

    onLeave() {
        this.state.hover = null;
    }

    onChartClick(ev) {
        const { index, status } = this.locate(ev);
        if (status) {
            this.open(this.state.data.days[index].date, status);
        }
    }

    open(date, status) {
        return this.props.onOpen("cfd_issues", [this.props.projectId, date, status]);
    }

    countText(day) {
        return this.state.data.statuses.map((s) => `${s.label} ${day.counts[s.code]}`).join(", ");
    }
}
