import { signal } from "@odoo/owl";
import { Component, onMounted, proxy, useProps, t } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { niceMax } from "./agile_cfd";
import { ReportExport, svgPngBlob } from "./report_export";


const CHART = { w: 720, h: 276, left: 48, right: 12, top: 12, bottom: 44 };

/** One column per day, week or month; the first and last label are enough for the axis. */
export function deployLayout(buckets) {
    const plotW = CHART.w - CHART.left - CHART.right;
    const plotH = CHART.h - CHART.top - CHART.bottom;
    const top = niceMax(Math.max(0, ...buckets.map((b) => b.count + b.failed)));
    const slot = plotW / Math.max(buckets.length, 1);
    const y = (value) => CHART.top + plotH - (plotH * value) / top;
    const bars = buckets.map((bucket, index) => ({
        bucket,
        x: CHART.left + slot * index + slot * 0.1,
        width: Math.max(slot * 0.8, 1),
        doneY: y(bucket.count),
        doneHeight: y(0) - y(bucket.count),
        failedY: y(bucket.count + bucket.failed),
        failedHeight: y(bucket.count) - y(bucket.count + bucket.failed),
    }));
    return { bars, top, y, plotW, plotH, chart: CHART };
}

/** "12 deploys to production, about 1 a week. The last one was 3 days ago." and what to do when there are none. */
export function deploySummary(data) {
    if (!data.any) {
        return _t("No deployments have been recorded for this project yet.");
    }
    const where = data.environment ? _t(" to %(environment)s", { environment: data.environment }) : "";
    if (!data.total) {
        return _t("No deploys%(where)s between these dates.", { where });
    }
    const last =
        data.days_since === 0
            ? _t("The last one was today.")
            : data.days_since === 1
              ? _t("The last one was yesterday.")
              : _t("The last one was %(days)s days ago.", { days: data.days_since });
    const failed = data.failed ? _t(" %(count)s failed.", { count: data.failed }) : "";
    return _t("%(count)s deploys%(where)s, about %(rate)s a week. %(last)s%(failed)s", {
        count: data.total,
        where,
        rate: data.per_week,
        last,
        failed,
    });
}

export class AgileDeploys extends Component {
    static template = "agile_community.Deploys";
    static components = { ReportExport };
    props = useProps({projectId: t.any()});

    setup() {
        this.orm = useService("orm");
        this.state = proxy({
            loading: true,
            error: null,
            data: null,
            from: "",
            to: "",
            environment: null,
            period: "week",
            hover: null,
            table: false,
        });
        this.chartBox = signal.ref();
        onMounted(() => this.load());
    }

    get layout() {
        return this.state.data?.buckets.length ? deployLayout(this.state.data.buckets) : null;
    }

    get summary() {
        return this.state.data ? deploySummary(this.state.data) : "";
    }

    get hoverBucket() {
        return this.state.hover === null ? null : this.state.data.buckets[this.state.hover];
    }

    get exportTitle() {
        const where = this.state.data?.environment;
        return where ? _t("Deployment frequency %(environment)s", { environment: where }) : _t("Deployment frequency");
    }

    exportTable() {
        const rows = this.state.data.buckets.map((b) => [b.date, b.count, b.failed]);
        return { columns: [_t("Period starting"), _t("Deployed"), _t("Failed")], rows };
    }

    exportPng() {
        return svgPngBlob(this.chartBox().querySelector("svg"), this.exportTitle, this.summary);
    }

    async load() {
        this.state.loading = true;
        this.state.error = null;
        try {
            const data = await this.orm.call("agile.report", "deploy_frequency", [
                this.props.projectId,
                this.state.from || false,
                this.state.to || false,
                this.state.environment,
                this.state.period,
            ]);
            this.state.data = data;
            this.state.from = data.from;
            this.state.to = data.to;
            this.state.environment = data.environment;
        } catch (error) {
            this.state.error = error?.data?.message || error?.message || _t("The report could not load. Try again.");
        } finally {
            this.state.loading = false;
        }
    }

    onChange(field, ev) {
        this.state[field] = ev.target.value;
        return this.load();
    }

    toggleTable() {
        this.state.table = !this.state.table;
    }

    onMove(ev) {
        const buckets = this.state.data.buckets;
        const box = ev.currentTarget.getBoundingClientRect();
        const px = ((ev.clientX - box.left) / box.width) * CHART.w;
        const slot = (CHART.w - CHART.left - CHART.right) / buckets.length;
        this.state.hover = Math.max(0, Math.min(buckets.length - 1, Math.floor((px - CHART.left) / slot)));
    }

    onLeave() {
        this.state.hover = null;
    }
}
