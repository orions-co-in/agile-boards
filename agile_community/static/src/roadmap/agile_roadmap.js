import { signal } from "@odoo/owl";
import { Component, onMounted, onWillDestroy, proxy, usePlugin, useProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { UIPlugin } from "@web/core/ui/ui_plugin";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

import { Layout } from "@web/search/layout";
import { browser } from "@web/core/browser/browser";
import { downloadText } from "../dashboard/dashboard_export";
import { AgilePlan } from "./agile_plan";
import { AgileRoadmapShare, STATUS_LABELS, barColour, colourLegend, releaseColours, shareIdFrom } from "./agile_roadmap_share";
import { ActionPlugin } from "@web/webclient/actions/action_plugin";

const DAY_MS = 86400000;
export const ROW_H = 48; // tall enough for a bar and an arrow running past it
export const ARROW_GAP = 12; // how far an arrow runs out of a bar and into the next
export const ZOOMS = { week: 24, month: 8, quarter: 3 }; // pixels per day

const dayNumber = (iso) => Math.round(Date.parse(`${iso}T00:00:00Z`) / DAY_MS);

/** The first and last day to draw: everything dated, today, and a little air on both sides. */
export function timeRange(data) {
    const days = [dayNumber(data.today)];
    for (const project of data.projects) {
        for (const row of project.rows) {
            for (const item of [row, ...row.children]) {
                if (item.start) {
                    days.push(dayNumber(item.start), dayNumber(item.end));
                }
            }
        }
    }
    for (const s of data.sprints) {
        days.push(dayNumber(s.start), dayNumber(s.end));
    }
    for (const r of data.releases) {
        days.push(dayNumber(r.date));
    }
    return { start: Math.min(...days) - 7, end: Math.max(...days) + 14 };
}

const dayDate = (day) => new Date(day * DAY_MS);

/** "3 Nov" for a date written 2026-11-03, in the browser's language. */
export function shortDate(iso) {
    return new Date(`${iso}T00:00:00Z`).toLocaleDateString(undefined, { day: "numeric", month: "short", timeZone: "UTC" });
}

/**
 * The date ruler: a mark and a label at every Monday (week and month zoom) or at the first of
 * each month (quarter zoom), with the pixel place of each.
 */
export function rulerTicks(range, zoom) {
    const px = ZOOMS[zoom];
    const ticks = [];
    for (let day = range.start; day <= range.end; day++) {
        const date = dayDate(day);
        const first = date.getUTCDate() === 1;
        if (zoom === "quarter" ? first : date.getUTCDay() === 1) {
            const options = zoom === "quarter" ? { month: "short", year: "numeric" } : { day: "numeric", month: "short" };
            ticks.push({ left: (day - range.start) * px, label: date.toLocaleDateString(undefined, { ...options, timeZone: "UTC" }), month: first });
        }
    }
    return ticks;
}

const DEPENDENCIES_KEY = "agile_community.roadmap.dependencies";

/** Whether the arrows are shown: on unless this browser stored "off". Unreadable storage means on. */
export function readShowDependencies(storage) {
    try {
        return storage.getItem(DEPENDENCIES_KEY) !== "off";
    } catch {
        return true;
    }
}

/** Remember the choice; blocked storage is ignored, the choice then lasts until the page closes. */
export function writeShowDependencies(storage, on) {
    try {
        storage.setItem(DEPENDENCIES_KEY, on ? "on" : "off");
    } catch {
        // storage is a convenience only
    }
}

/** Horizontal place of a date span: left edge and width in pixels. */
export function barBox(range, zoom, start, end) {
    const px = ZOOMS[zoom];
    const left = (dayNumber(start) - range.start) * px;
    return { left, width: Math.max((dayNumber(end) - dayNumber(start) + 1) * px, 6) };
}

/**
 * Rows to draw, top to bottom: a heading per project when several are shown, each epic, and the
 * issues of the epics that are expanded. Each row has the item it shows and its index.
 */
export function visibleRows(data, expanded) {
    const rows = [];
    for (const project of data.projects) {
        if (data.multi) {
            rows.push({ type: "project", id: project.id, name: project.name, rollup: project.rollup, index: rows.length });
        }
        for (const epic of project.rows) {
            rows.push({ type: epic.kind, item: epic, index: rows.length, project: project.name, canMove: !!project.can_move });
            if (expanded.has(`${epic.kind}:${epic.id}`)) {
                for (const issue of epic.children) {
                    rows.push({ type: "issue", item: issue, index: rows.length, parent: epic, project: project.name, canMove: !!project.can_move });
                }
            }
        }
    }
    return rows;
}

/**
 * Arrows from the end of a blocker to the start of what it blocks. An item inside a collapsed
 * epic is drawn on its epic's row. Hidden blockers become a stub on the blocked item's row.
 */
export function dependencyLines(data, rows, range, zoom) {
    const rowOf = new Map();
    for (const row of rows) {
        if (row.item) {
            rowOf.set(row.item.id, row);
            for (const child of row.item.children || []) {
                if (!rowOf.has(child.id)) {
                    rowOf.set(child.id, row);
                }
            }
        }
    }
    // An issue's own row wins over its epic's row.
    for (const row of rows) {
        if (row.type === "issue") {
            rowOf.set(row.item.id, row);
        }
    }
    const lines = [];
    for (const dep of data.dependencies) {
        const to = rowOf.get(dep.to);
        if (!to) {
            continue;
        }
        const toItem = to.item;
        const toX = barBox(range, zoom, toItem.start, toItem.end).left;
        const toY = to.index * ROW_H + ROW_H / 2;
        if (dep.hidden) {
            lines.push({ ...dep, stub: true, x: toX, y: toY, path: `M ${toX - 14} ${toY} L ${toX} ${toY}` });
            continue;
        }
        const from = rowOf.get(dep.from);
        if (!from || from === to) {
            continue;
        }
        const fromItem = from.item;
        const box = barBox(range, zoom, fromItem.start, fromItem.end);
        const fromX = box.left + box.width;
        const fromY = from.index * ROW_H + ROW_H / 2;
        let path;
        if (toX - ARROW_GAP >= fromX + ARROW_GAP) {
            path = `M ${fromX} ${fromY} H ${toX - ARROW_GAP} V ${toY} H ${toX}`;
        } else {
            // The blocked bar starts before the blocker ends: leave to the right, run along the edge of the
            // blocked row (never across its bar), then come in from the left.
            const edge = to.index > from.index ? toY - ROW_H / 2 : toY + ROW_H / 2;
            path = `M ${fromX} ${fromY} H ${fromX + ARROW_GAP} V ${edge} H ${toX - ARROW_GAP} V ${toY} H ${toX}`;
        }
        lines.push({ ...dep, stub: false, path });
    }
    return lines;
}

/** "6 of 9 done" for an epic, empty for anything else. */
/** Index of the bar to focus after a key press, or null when the key is not a movement key. */
export function nextBarIndex(count, index, key) {
    if (!count) {
        return null;
    }
    const last = count - 1;
    switch (key) {
        case "ArrowDown":
        case "ArrowRight":
            return Math.min(last, index + 1);
        case "ArrowUp":
        case "ArrowLeft":
            return Math.max(0, index - 1);
        case "Home":
            return 0;
        case "End":
            return last;
        default:
            return null;
    }
}

export function progressText(item) {
    return item.kind === "epic" && item.total ? _t("%(done)s of %(total)s done", { done: item.done, total: item.total }) : "";
}

/** One project's progress for its heading: "3 of 5 epics done, 18 of 40 issues done". */
export function rollupText(rollup) {
    if (!rollup || (!rollup.epics_total && !rollup.issues_total)) {
        return _t("No issues yet");
    }
    return _t("%(epics_done)s of %(epics_total)s epics done, %(issues_done)s of %(issues_total)s issues done", rollup);
}

/** "Starts 7 days before QA-12 ends. Earliest valid start 2026-11-14." */
export function collisionText(collision) {
    return collision.days === 1
        ? _t("Starts 1 day before %(key)s ends. Earliest valid start %(date)s.", { key: collision.blocker_key, date: collision.earliest_start })
        : _t("Starts %(days)s days before %(key)s ends. Earliest valid start %(date)s.", {
              days: collision.days, key: collision.blocker_key, date: collision.earliest_start,
          });
}

/** The words of the "starts too early" popover for one blocked item. */
export function warningText(item) {
    const c = item.collision;
    const lead = c.days === 1
        ? _t("Starts 1 day before %(blocker)s ends.", { blocker: c.blocker_key })
        : _t("Starts %(days)s days before %(blocker)s ends.", { days: c.days, blocker: c.blocker_key });
    const earliest = c.new_end
        ? _t("Earliest valid start: %(date)s (the day after the last blocker ends). Moving the start keeps the length, so the end moves from %(oldEnd)s to %(newEnd)s.", {
              date: shortDate(c.earliest_start), oldEnd: shortDate(item.end), newEnd: shortDate(c.new_end),
          })
        : _t("Earliest valid start: %(date)s (the day after the last blocker ends).", { date: shortDate(c.earliest_start) });
    return {
        title: _t("%(key)s starts too early", { key: item.key }),
        lead,
        detail: _t("%(blocker)s ends %(end)s; %(key)s starts %(start)s.", {
            blocker: c.blocker_key, end: shortDate(c.blocker_end), key: item.key, start: shortDate(item.start),
        }),
        earliest,
    };
}

/** The sentence a bar reads out: key, name, dates, progress and what is wrong. */
export function describeItem(item) {
    const parts = [`${item.key} ${item.name}`.trim(), _t("%(start)s to %(end)s", { start: item.start, end: item.end })];
    const progress = progressText(item);
    if (progress) {
        parts.push(progress);
    }
    if (item.collision) {
        parts.push(collisionText(item.collision));
    } else if (item.late) {
        // An epic turns red when an issue inside it is blocked, even if nothing blocks the epic itself.
        parts.push(_t("Contains an issue that starts before its blocker ends"));
    }
    if (item.circular) {
        parts.push(_t("Circular dependency"));
    }
    return parts.join(". ");
}

export class AgileRoadmap extends Component {
    static template = "agile_community.Roadmap";
    static displayName = _t("Roadmap");
    static components = { Layout, AgilePlan, AgileRoadmapShare };
    props = useProps();

    setup() {
        this.orm = useService("orm");
        this.action = usePlugin(ActionPlugin);
        this.ui = usePlugin(UIPlugin);
        this.display = { controlPanel: {} };
        this.state = proxy({
            loading: true,
            error: null,
            data: null,
            projects: [],
            selected: [],
            zoom: "month",
            epicsOnly: false,
            hideDone: false,
            asList: false,
            view: "timeline",
            showDependencies: readShowDependencies(browser.localStorage),
            expanded: new Set(),
            focus: null,
            panel: null,
            printing: false,
            warning: null,
            exportNotice: null,
            colourBy: "default",
            sharing: false,
            share: null,
            hiddenProjects: 0,
        });
        this.shareId = shareIdFrom(this.props.action?.params, browser.location.search);
        this.root = signal.ref();
        this.searchToken = 0;
        onMounted(() => this.start());
        onWillDestroy(() => clearTimeout(this.undoTimer));
    }

    /** Arrow keys, Home and End move focus between the bars, in reading order. */
    onBarKeydown(ev) {
        const bars = [...(this.root()?.querySelectorAll(".o_ag_rm_bar") || [])];
        const target = nextBarIndex(bars.length, bars.indexOf(ev.currentTarget), ev.key);
        if (target === null) {
            return;
        }
        ev.preventDefault();
        bars[target].focus();
        bars[target].scrollIntoView({ block: "nearest", inline: "nearest" });
    }

    get initialProjects() {
        const action = this.props.action || {};
        return action.params?.project_ids || (action.context?.active_id ? [action.context.active_id] : []);
    }

    /** Opened from a project's sidebar: the roadmap is that project's only, so no project picker. */
    get inProject() {
        return this.initialProjects.length === 1;
    }

    get pageTitle() {
        const projects = this.state.data?.projects || [];
        if (this.state.share) {
            return this.state.share.name;
        }
        return this.inProject && projects.length === 1 && projects[0].name
            ? _t("Roadmap: %(project)s", { project: projects[0].name })
            : _t("Roadmap");
    }

    /** One line when the arrows cannot be seen: why there are none, or that they are switched off. */
    get dependencyNotice() {
        if (!this.state.data || this.isList || this.isEmpty) {
            return "";
        }
        if (!this.state.showDependencies) {
            const any = dependencyLines(this.state.data, this.rows, this.range, this.state.zoom).length;
            return any ? _t("Dependencies are hidden. Turn them on to see what blocks what.") : "";
        }
        return this.lines.length ? "" : _t("No dependencies in this view.");
    }

    async start() {
        this.state.selected = [...this.initialProjects];
        try {
            this.state.projects = await this.orm.call("agile.roadmap", "roadmap_projects", []);
        } catch {
            this.state.projects = [];
        }
        await this.load();
    }

    async load() {
        this.state.loading = true;
        this.state.error = null;
        try {
            if (this.shareId) {
                await this.loadShared();
            } else {
                this.state.data = await this.orm.call("agile.roadmap", "roadmap_data", [], {
                    project_ids: this.state.selected,
                    hide_done: this.state.hideDone,
                    epics_only: this.state.epicsOnly,
                });
            }
        } catch (error) {
            this.state.data = null;
            this.state.error = this.shareId
                ? error?.data?.message || _t("This shared roadmap did not load. Try again.")
                : _t("The roadmap did not load. Try again.");
        } finally {
            this.state.loading = false;
        }
    }

    /** A roadmap shared by someone else: their saved projects and options, read only. */
    async loadShared() {
        const result = await this.orm.call("agile.roadmap.share", "share_data", [this.shareId]);
        Object.assign(this.state, {
            data: result.data,
            share: result.share,
            hiddenProjects: result.hidden_projects,
            hideDone: result.share.hide_done,
            epicsOnly: result.share.epics_only,
            selected: result.data.projects.map((project) => project.id),
        });
        if (this.state.colourBy === "default") {
            this.state.colourBy = result.share.colour_by;
        }
    }

    get isShared() {
        return !!this.shareId;
    }

    /** The projects a new share saves: the picked ones, or every project the person can see. */
    get shareProjects() {
        return this.state.selected.length ? this.state.selected : this.state.projects.map((project) => project.id);
    }

    get releases() {
        return releaseColours(this.state.data);
    }

    get legend() {
        return colourLegend(this.state.colourBy, this.releases, this.state.data);
    }

    /** The bar's colour as a CSS variable; none keeps the standard look. */
    barVars(item) {
        const colour = barColour(item, this.state.colourBy, this.releases);
        return colour ? `--rm-colour: ${colour};` : "";
    }

    toggleSharing() {
        this.state.sharing = !this.state.sharing;
    }

    get isPlan() {
        return this.state.view === "plan";
    }

    setView(view) {
        this.state.view = view;
    }

    get isList() {
        return this.state.asList || this.ui.isSmall() || this.state.printing;
    }

    get isEmpty() {
        return !!this.state.data && !this.state.data.projects.some((p) => p.rows.length);
    }

    get range() {
        return timeRange(this.state.data);
    }

    get rows() {
        return visibleRows(this.state.data, this.state.printing ? this.allKeys() : this.state.expanded);
    }

    get lines() {
        return this.state.showDependencies ? dependencyLines(this.state.data, this.rows, this.range, this.state.zoom) : [];
    }

    /** Every epic and "No epic" group, so a printed page shows all their issues. */
    allKeys() {
        const keys = new Set();
        for (const project of this.state.data.projects) {
            for (const row of project.rows) {
                keys.add(`${row.kind}:${row.id}`);
            }
        }
        return keys;
    }

    /** The CSV of what the screen shows: same projects, Hide done and Epics only. */
    async downloadCsv() {
        this.state.exportNotice = null;
        try {
            const result = await this.orm.call("agile.roadmap", "roadmap_csv", [], {
                project_ids: this.state.selected,
                hide_done: this.state.hideDone,
                epics_only: this.state.epicsOnly,
            });
            if (!result.count) {
                this.state.exportNotice = _t("Nothing to export: no scheduled items on this view.");
                return;
            }
            downloadText(result.filename, result.content);
            this.state.exportNotice = _t("Downloaded %(name)s with %(count)s items.", { name: result.filename, count: result.count });
        } catch (error) {
            this.state.exportNotice = this.errorText(error, _t("The export failed. Try again."));
        }
    }

    /** Show the list form with every epic open, then hand the page to the browser's print dialog. */
    printLayout() {
        this.state.exportNotice = null;
        this.state.printing = true;
        const done = () => {
            this.state.printing = false;
        };
        window.addEventListener("afterprint", done, { once: true });
        // Let the list form render before the dialog freezes the page.
        setTimeout(() => window.print(), 150);
    }

    toggleDependencies() {
        this.state.showDependencies = !this.state.showDependencies;
        writeShowDependencies(browser.localStorage, this.state.showDependencies);
    }

    get canvasWidth() {
        const range = this.range;
        return (range.end - range.start + 1) * ZOOMS[this.state.zoom];
    }

    /** The marker that says where today is, in pixels. */
    get todayLeft() {
        return (dayNumber(this.state.data.today) - this.range.start) * ZOOMS[this.state.zoom];
    }

    box(start, end) {
        return barBox(this.range, this.state.zoom, start, end);
    }

    releaseLeft(release) {
        return this.box(release.date, release.date).left;
    }

    fill(item) {
        return item.total ? Math.round((100 * item.done) / item.total) : 0;
    }

    warningText(item) {
        return warningText(item);
    }

    shortDate(iso) {
        return shortDate(iso);
    }

    /** A click on a bar that starts too early opens the warning; any other bar opens its issue. */
    onBar(row, ev) {
        if (row.item.collision) {
            this.openWarning(row, ev.currentTarget);
        } else {
            this.open(row.item);
        }
    }

    /** Opens the warning under the bar (or above it when the page ends too soon), fixed on screen so no scroll area clips it. */
    openWarning(row, target) {
        const bar = this.root()?.querySelector(`.o_ag_rm_bar[data-id="${row.item.id}"]`) || target;
        const rect = bar.getBoundingClientRect();
        const below = window.innerHeight - rect.bottom;
        this.state.warning = {
            item: row.item, canMove: row.canMove, moved: null, notice: null,
            left: Math.max(8, Math.min(rect.left, window.innerWidth - 400)),
            top: below >= 330 || rect.top < 330 ? rect.bottom + 6 : null,
            bottom: below >= 330 || rect.top < 330 ? null : window.innerHeight - rect.top + 6,
        };
    }

    closeWarning() {
        const id = this.state.warning?.item.id;
        this.state.warning = null;
        // Back to the bar the warning came from, so keyboard use carries on from there.
        this.root()?.querySelector(`.o_ag_rm_bar[data-id="${id}"]`)?.focus();
    }

    onWarningKeydown(ev) {
        if (ev.key === "Escape") {
            this.closeWarning();
        }
    }

    async moveFromWarning() {
        const warning = this.state.warning;
        try {
            const result = await this.orm.call("agile.roadmap", "move_to_earliest_start", [warning.item.id, warning.item.start]);
            warning.moved = result;
            warning.notice = _t("Moved %(key)s from %(old)s to %(new)s.", {
                key: warning.item.key, old: shortDate(result.old.start), new: shortDate(result.new.start),
            });
            await this.load();
        } catch (error) {
            warning.notice = this.errorText(error, _t("Could not move the start."));
        }
    }

    async undoFromWarning() {
        const warning = this.state.warning;
        const moved = warning.moved;
        try {
            await this.orm.call("agile.roadmap", "undo_move_start", [warning.item.id, moved.old.start, moved.old.end, moved.new.start]);
            this.state.warning = null;
            await this.load();
        } catch (error) {
            warning.notice = this.errorText(error, _t("Could not put the start back."));
        }
    }

    get rowH() {
        return ROW_H;
    }

    get ticks() {
        return rulerTicks(this.range, this.state.zoom);
    }

    shortDate(iso) {
        return shortDate(iso);
    }

    /** The bar's label; with colours on it also says the status or release, so colour is never the only clue. */
    describe(item) {
        const text = describeItem(item);
        if (this.state.colourBy === "status" && STATUS_LABELS[item.status]) {
            return `${text}. ${STATUS_LABELS[item.status]}`;
        }
        if (this.state.colourBy === "release") {
            return `${text}. ${item.release || _t("No release")}`;
        }
        return text;
    }

    collisionText(collision) {
        return collisionText(collision);
    }

    /** The "Blocked by" lines of a list row: the open blockers and when each ends. */
    blockedByText(item) {
        return item.blocked_by
            .map((b) => _t("%(key)s ends %(end)s", { key: b.key, end: b.end }) + (this.state.data.multi ? ` (${b.project})` : ""))
            .join(", ");
    }

    progress(item) {
        return progressText(item);
    }

    toggle(item) {
        const key = `${item.kind}:${item.id}`;
        const expanded = new Set(this.state.expanded);
        expanded.has(key) ? expanded.delete(key) : expanded.add(key);
        this.state.expanded = expanded;
    }

    isOpen(item) {
        return this.state.expanded.has(`${item.kind}:${item.id}`);
    }

    setZoom(zoom) {
        this.state.zoom = zoom;
    }

    async setOption(name, ev) {
        this.state[name] = ev.target.checked;
        await this.load();
    }

    async onProjects(ev) {
        this.state.selected = [...ev.target.selectedOptions].map((o) => parseInt(o.value, 10));
        await this.load();
    }

    focusLines(item) {
        this.state.focus = item ? item.id : null;
    }

    lineClass(line) {
        const faded = this.state.focus && line.from !== this.state.focus && line.to !== this.state.focus;
        return `o_ag_rm_line ${line.late ? "late" : ""} ${line.stub ? "stub" : ""} ${faded ? "faded" : ""}`;
    }

    lineTitle(line) {
        if (line.hidden) {
            return _t("Blocked by an issue you cannot see");
        }
        const where = this.state.data.multi ? ` (${line.from_project})` : "";
        return line.late
            ? _t("Blocked by %(key)s%(where)s, ends %(end)s, after this starts", { key: line.from_key, where, end: line.from_end })
            : _t("Blocked by %(key)s%(where)s, ends %(end)s", { key: line.from_key, where, end: line.from_end });
    }

    async open(item) {
        if (!item.id) {
            return;
        }
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "project.task",
            res_id: item.id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    // ---- The Blockers panel (P-921): list, add, remove and undo the blockers of one issue ----

    /** Rows that can have blockers: real issues and epics, not the "No epic" group. */
    canHaveBlockers(item) {
        return !!item.id;
    }

    async openPanel(item) {
        this.state.panel = { id: item.id, key: item.key, name: item.name, moved: null, data: null, error: null, term: "", results: [], notice: null, undoId: null };
        await this.refreshPanel();
    }

    closePanel() {
        clearTimeout(this.undoTimer);
        this.state.panel = null;
    }

    onPanelKeydown(ev) {
        if (ev.key === "Escape") {
            this.closePanel();
        }
    }

    async refreshPanel() {
        const panel = this.state.panel;
        panel.error = null;
        try {
            panel.data = await this.orm.call("agile.roadmap", "blockers", [panel.id]);
        } catch {
            panel.error = _t("The blockers did not load. Try again.");
        }
    }

    async searchBlockers(term) {
        const panel = this.state.panel;
        panel.term = term;
        const token = ++this.searchToken;
        const results = await this.orm.call("agile.roadmap", "search_blockers", [panel.id, term]);
        if (token === this.searchToken && this.state.panel === panel) {
            panel.results = results;
        }
    }

    /** The server's own sentence when it refused, a plain fallback otherwise. */
    errorText(error, fallback) {
        return error?.data?.message || fallback;
    }

    async addBlocker(blocker, { undo = false } = {}) {
        const panel = this.state.panel;
        try {
            panel.data = await this.orm.call("agile.roadmap", "add_blocker", [panel.id, blocker.id]);
            panel.notice = undo ? _t("Put %(key)s back as a blocker.", { key: blocker.key }) : _t("Added %(key)s as a blocker.", { key: blocker.key });
            panel.undoId = null;
            panel.term = "";
            panel.results = [];
            await this.load();
        } catch (error) {
            panel.notice = this.errorText(error, _t("Could not add the blocker."));
        }
    }

    async removeBlocker(blocker) {
        const panel = this.state.panel;
        try {
            panel.data = await this.orm.call("agile.roadmap", "remove_blocker", [panel.id, blocker.id]);
            panel.notice = _t("Removed %(key)s.", { key: blocker.key });
            panel.undoId = blocker;
            clearTimeout(this.undoTimer);
            this.undoTimer = setTimeout(() => {
                if (this.state.panel === panel) {
                    panel.undoId = null;
                }
            }, 8000);
            await this.load();
        } catch (error) {
            panel.notice = this.errorText(error, _t("Could not remove the blocker."));
        }
    }

    undoRemove() {
        const blocker = this.state.panel.undoId;
        if (blocker) {
            return this.addBlocker(blocker, { undo: true });
        }
    }

    /** Move the start to the earliest valid day; the dates shown are the ones the person saw. */
    async moveStart() {
        const panel = this.state.panel;
        const start = panel.data.start;
        try {
            const result = await this.orm.call("agile.roadmap", "move_to_earliest_start", [panel.id, start]);
            panel.data = result.panel;
            panel.moved = result;
            panel.notice = _t("Moved the start from %(old)s to %(new)s.", { old: result.old.start, new: result.new.start });
            await this.load();
        } catch (error) {
            panel.notice = this.errorText(error, _t("Could not move the start."));
        }
    }

    async undoMove() {
        const panel = this.state.panel;
        const moved = panel.moved;
        try {
            panel.data = await this.orm.call("agile.roadmap", "undo_move_start", [panel.id, moved.old.start, moved.old.end, moved.new.start]);
            panel.moved = null;
            panel.notice = _t("Put the start back to %(old)s.", { old: moved.old.start });
            await this.load();
        } catch (error) {
            panel.notice = this.errorText(error, _t("Could not put the start back."));
        }
    }

    async openProject(row) {
        const action = await this.orm.call("project.project", "action_open_agile_roadmap_page", [[row.id]]);
        await this.action.doAction(action);
    }

    rollupText(rollup) {
        return rollupText(rollup);
    }

    openUnscheduled() {
        const id = this.state.data.projects[0]?.id;
        if (id) {
            this.orm.call("project.project", "action_view_agile_unscheduled_issues", [[id]]).then((a) => this.action.doAction(a));
        }
    }
}

registry.category("actions").add("agile_community.roadmap", AgileRoadmap);
