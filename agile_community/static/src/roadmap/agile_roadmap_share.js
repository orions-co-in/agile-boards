// Roadmap colours and shared views (U-1163). The pure helpers are tested on their own.
import { Component, onMounted, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { browser } from "@web/core/browser/browser";

// Eight colours that stay apart for most kinds of colour blindness; the legend names each one.
export const RELEASE_COLOURS = ["#0b5ed7", "#c2410c", "#157347", "#7a46c9", "#b4236a", "#0e7490", "#96620a", "#5d6975"];
export const STATUS_LABELS = {
    backlog: _t("Backlog"),
    ready: _t("To Do"),
    progress: _t("In Progress"),
    review: _t("Review"),
    done: _t("Done"),
    canceled: _t("Canceled"),
};

/** Releases that appear on the bars, by name, each with its colour (the colours repeat after eight). */
export function releaseColours(data) {
    const found = new Map();
    for (const project of data?.projects || []) {
        for (const row of project.rows) {
            for (const item of [row, ...(row.children || [])]) {
                if (item.release_id && !found.has(item.release_id)) {
                    found.set(item.release_id, { id: item.release_id, name: item.release });
                }
            }
        }
    }
    const sorted = [...found.values()].sort((a, b) => a.name.localeCompare(b.name) || a.id - b.id);
    return new Map(sorted.map((release, index) => [release.id, { ...release, colour: RELEASE_COLOURS[index % 8] }]));
}

/** The colour of one bar for the chosen mode, or "" to keep the standard look. */
export function barColour(item, mode, releases) {
    if (mode === "status" && STATUS_LABELS[item.status]) {
        return `var(--ag-s-${item.status})`;
    }
    if (mode === "release" && item.release_id) {
        return releases.get(item.release_id)?.colour || "";
    }
    return "";
}

/** The legend under the toolbar: one swatch and name for each colour in use. */
export function colourLegend(mode, releases, data) {
    if (mode === "status") {
        return Object.entries(STATUS_LABELS).map(([code, label]) => ({ key: code, label, colour: `var(--ag-s-${code})` }));
    }
    if (mode === "release") {
        const entries = [...releases.values()].map((r) => ({ key: r.id, label: r.name, colour: r.colour }));
        const without = (data?.projects || []).some((p) =>
            p.rows.some((row) => [row, ...(row.children || [])].some((item) => item.start && !item.release_id))
        );
        return without ? [...entries, { key: 0, label: _t("No release"), colour: "" }] : entries;
    }
    return [];
}

/** Where a shared roadmap opens. The page reads `roadmap_share` from the address. */
export function shareLink(origin, shareId) {
    return `${origin}/odoo/action-agile_community.agile_roadmap_page_action?roadmap_share=${shareId}`;
}

/** The share id the page was opened with: from an action's params or from the address. */
export function shareIdFrom(params, search) {
    const raw = params?.share_id ?? new URLSearchParams(search || "").get("roadmap_share");
    const id = parseInt(raw, 10);
    return Number.isInteger(id) && id > 0 ? id : null;
}

export class AgileRoadmapShare extends Component {
    static template = "agile_community.RoadmapShare";
    static props = {
        projects: Array,
        hideDone: Boolean,
        epicsOnly: Boolean,
        colourBy: String,
        onClose: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            loading: true,
            error: null,
            mine: [],
            shared: [],
            people: [],
            name: "",
            chosen: [],
            notice: "",
            editing: null,
        });
        onMounted(() => this.load());
    }

    async load() {
        try {
            const result = await this.orm.call("agile.roadmap.share", "share_list", []);
            Object.assign(this.state, { mine: result.mine, shared: result.shared, people: result.people, error: null });
        } catch (error) {
            this.state.error = error?.data?.message || _t("The shared roadmaps did not load. Try again.");
        } finally {
            this.state.loading = false;
        }
    }

    toggle(list, id) {
        const at = list.indexOf(id);
        at < 0 ? list.push(id) : list.splice(at, 1);
    }

    async create(ev) {
        ev.preventDefault();
        try {
            await this.orm.call("agile.roadmap.share", "share_create", [
                this.state.name,
                this.props.projects,
                this.state.chosen,
                this.props.hideDone,
                this.props.epicsOnly,
                this.props.colourBy,
            ]);
            Object.assign(this.state, { name: "", chosen: [], error: null, notice: _t("Shared. Copy the link to send it.") });
            await this.load();
        } catch (error) {
            this.state.error = error?.data?.message || _t("The roadmap could not be shared. Try again.");
        }
    }

    startEdit(share) {
        this.state.editing = { id: share.id, chosen: [...share.user_ids] };
    }

    async saveEdit() {
        try {
            await this.orm.call("agile.roadmap.share", "share_update", [this.state.editing.id, this.state.editing.chosen]);
            this.state.editing = null;
            this.state.error = null;
            await this.load();
        } catch (error) {
            this.state.error = error?.data?.message || _t("The change could not be saved. Try again.");
        }
    }

    async remove(share) {
        await this.orm.call("agile.roadmap.share", "share_delete", [share.id]);
        this.state.notice = _t("Stopped sharing %(name)s.", { name: share.name });
        await this.load();
    }

    async copyLink(share) {
        const link = shareLink(browser.location.origin, share.id);
        try {
            await browser.navigator.clipboard.writeText(link);
            this.state.notice = _t("Link copied.");
        } catch {
            this.state.notice = link; // clipboard blocked: show the link to copy by hand
        }
    }

    open(share) {
        this.props.onClose();
        return this.action.doAction({
            type: "ir.actions.client",
            tag: "agile_community.roadmap",
            name: share.name,
            params: { share_id: share.id },
        });
    }
}
