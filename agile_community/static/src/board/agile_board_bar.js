import { Component, onMounted, onWillStart, onWillUpdateProps, useRef, useState } from "@odoo/owl";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { _t } from "@web/core/l10n/translation";
import { browser } from "@web/core/browser/browser";

// Chips that are plain filters of the search view, by chip key.
const NAMED_FILTERS = {
    mine: "agile_quick_my_issues",
    blocked: "agile_blocked",
    flagged: "agile_flagged",
    review: "agile_my_review",
    due: "agile_my_due_soon",
    canceled: "agile_show_canceled",
};

export const SWIMLANES = [
    { value: "none", label: _t("None") },
    { value: "assignee", label: _t("Assignee") },
    { value: "epic", label: _t("Epic") },
    { value: "priority", label: _t("Priority") },
    { value: "component", label: _t("Component") },
    { value: "label", label: _t("Label") },
];

/**
 * Filter chips and the swimlane choice above the board. Chips are ordinary search
 * facets, so they can be removed in the search box; the choice is remembered per
 * person and project on the server and applied again the next time the board opens.
 */
export class AgileBoardBar extends Component {
    static template = "agile_community.BoardBar";
    static components = { Dropdown, DropdownItem };
    static props = {
        projectId: Number,
        // Changes whenever the active filters change, so the bar redraws.
        filterKey: String,
        swimlane: String,
        onSwimlane: Function,
        onColumns: { type: Function, optional: true },
        selecting: { type: Boolean, optional: true },
        onSelect: { type: Function, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.swimlanes = SWIMLANES;
        this.state = useState({
            barOpen: false,
            types: [], epics: [], sprints: [], laneFilters: [], failed: false,
            views: [], saving: false, viewName: "", viewError: "", announce: "",
            query: null, canEditQuery: false, queryChoices: [], boards: [], board: null,
            insightsOpen: false, insights: null, insightsFailed: false,
            compact: this.readCompact(),
        });
        this.root = useRef("root");
        this.ready = false;
        this.savedKey = null;
        this.saved = null;
        onWillStart(() => this.loadOptions());
        onMounted(() => {
            this.applyCompact();
            this.applySaved();
        });
        onWillUpdateProps(() => {
            const keys = this.activeKeys();
            if (this.ready && this.keyString(keys) !== this.savedKey) {
                this.save({ filters: keys });
            }
        });
    }

    // ---- compact cards (U-1455): remembered in this browser, per person and project ----

    get compactStorageKey() {
        return `agile.compact.${user.userId}.${this.props.projectId}`;
    }

    readCompact() {
        try {
            return browser.localStorage.getItem(this.compactStorageKey) === "1";
        } catch {
            return false;
        }
    }

    applyCompact() {
        this.root.el?.closest(".o_kanban_view, .o_view_controller")?.classList.toggle("o_ag_compact", this.state.compact);
    }

    /** On a phone the filter chips start folded so the board stays on screen (NU-38). */
    toggleBar() {
        this.state.barOpen = !this.state.barOpen;
    }

    toggleCompact() {
        this.state.compact = !this.state.compact;
        try {
            browser.localStorage.setItem(this.compactStorageKey, this.state.compact ? "1" : "0");
        } catch {
            // Private windows can refuse storage; the choice then lasts until the board closes.
        }
        this.applyCompact();
    }

    get searchModel() {
        return this.env.searchModel;
    }

    get showCanceled() {
        return this.hasFilter("canceled");
    }

    /** A chip shows only when its filter is in the search view (some depend on the person's role). */
    hasFilter(key) {
        return Boolean(this.namedFilter(NAMED_FILTERS[key]));
    }

    async loadOptions() {
        try {
            this.saved = await this.orm.call("project.project", "agile_board_options", [[this.props.projectId]]);
            this.state.types = this.saved.task_types;
            this.state.epics = this.saved.epics;
            this.state.sprints = this.saved.sprints || [];
            this.state.laneFilters = this.saved.lane_filters || [];
            this.state.views = this.saved.views || [];
            this.state.query = this.saved.query || null;
            this.state.canEditQuery = Boolean(this.saved.can_edit_query);
            this.state.queryChoices = this.saved.query_choices || [];
            this.state.boards = this.saved.boards || [];
            this.state.board = this.saved.board || null;
        } catch {
            // The board works without the bar's pick lists; chips for Mine and Blocked still do.
            this.state.failed = true;
        }
    }

    applySaved() {
        const keys = this.saved?.filters || [];
        const wanted = keys.filter((key) => this.knownKey(key));
        for (const key of wanted.filter((key) => !key.startsWith("sprint:"))) {
            this.setKey(key, true);
        }
        this.setSprints(wanted.filter((key) => key.startsWith("sprint:")).map((key) => Number(key.split(":")[1])));
        this.applyQuery();
        this.props.onColumns?.(this.state.board?.column_ids || [], this.state.board?.column_groups || []);
        this.ready = true;
        this.savedKey = this.keyString(this.activeKeys());
        if (this.saved && this.saved.swimlane !== this.props.swimlane) {
            this.props.onSwimlane(this.saved.swimlane);
        }
    }

    knownKey(key) {
        if (key in NAMED_FILTERS) {
            return true;
        }
        const [kind, id] = key.split(":");
        const list = this.listFor(kind);
        return list.some((item) => String(item.id) === id);
    }

    listFor(kind) {
        return { type: this.state.types, epic: this.state.epics, sprint: this.state.sprints }[kind] || [];
    }

    keyString(keys) {
        return keys.join(",");
    }

    // ---- reading the search model ----

    namedFilter(name) {
        return this.searchModel.getSearchItems((item) => item.type === "filter" && item.name === name).at(0);
    }

    boardFilters() {
        return this.searchModel.getSearchItems(
            (item) => item.type === "filter" && (item.agileBoardKey || item.agileBoardKeys)
        );
    }

    activeKeys() {
        const keys = [];
        for (const [key, name] of Object.entries(NAMED_FILTERS)) {
            if (this.namedFilter(name)?.isActive) {
                keys.push(key);
            }
        }
        for (const item of this.boardFilters()) {
            if (item.isActive) {
                keys.push(...(item.agileBoardKeys || [item.agileBoardKey]));
            }
        }
        return keys;
    }

    isOn(key) {
        return this.activeKeys().includes(key);
    }

    isPicked(kind, id) {
        return this.activeOf(kind) === String(id);
    }

    activeOf(kind) {
        const key = this.activeKeys().find((value) => value.startsWith(kind + ":"));
        return key ? key.split(":")[1] : "";
    }

    // ---- several boards (R-1107): the switcher, and a manager's list of boards ----

    get currentBoardId() {
        return String(this.state.board?.id || 0);
    }

    /** R-1109: three plain numbers about the work on the board, loaded when the panel opens. */
    async toggleInsights() {
        this.state.insightsOpen = !this.state.insightsOpen;
        if (this.state.insightsOpen) {
            await this.loadInsights();
        }
    }

    async loadInsights() {
        try {
            this.state.insights = await this.orm.call("project.project", "agile_board_insights", [[this.props.projectId]]);
            this.state.insightsFailed = false;
        } catch {
            this.state.insights = null;
            this.state.insightsFailed = true;
        }
    }

    get cycleBars() {
        const series = this.state.insights?.cycle_time?.series || [];
        const top = Math.max(1, ...series.map((week) => week.average || 0));
        return series.map((week) => ({
            week: week.week,
            height: week.average ? Math.max(8, Math.round((100 * week.average) / top)) : 0,
            label: week.average === null
                ? _t("%(week)s: nothing finished", { week: week.week })
                : _t("Week of %(week)s: %(days)s days on average, %(count)s finished", {
                      week: week.week, days: week.average, count: week.count,
                  }),
        }));
    }

    get trendText() {
        const cycle = this.state.insights?.cycle_time;
        if (!cycle || cycle.recent_average === null) {
            return _t("Not enough finished work yet.");
        }
        const words = {
            faster: _t("Getting faster"),
            slower: _t("Getting slower"),
            steady: _t("Steady"),
            unknown: _t("Too early to tell"),
        };
        return _t("%(average)s days on average. %(trend)s.", { average: cycle.recent_average, trend: words[cycle.trend] });
    }

    isCurrentBoard(board) {
        return (board.id || 0) === (this.state.board?.id || 0);
    }

    /** Switch to another board: the server remembers it, then the bar reads the board's settings again. */
    async onBoardPick(ev) {
        const id = Number(ev.target.value) || false;
        try {
            await this.orm.call("project.project", "agile_board_switch", [[this.props.projectId]], { board_id: id });
            await this.reloadBoardOptions();
            this.state.announce = _t("Showing %(name)s.", { name: this.state.board?.name || _t("Default board") });
        } catch (error) {
            this.state.announce = error?.data?.message || _t("Could not switch the board. Try again.");
        }
    }

    async reloadBoardOptions() {
        this.saved = await this.orm.call("project.project", "agile_board_options", [[this.props.projectId]]);
        this.state.boards = this.saved.boards || [];
        this.state.board = this.saved.board || null;
        this.state.query = this.saved.query || null;
        this.state.queryChoices = this.saved.query_choices || [];
        this.applyQuery();
        this.props.onColumns?.(this.state.board?.column_ids || [], this.state.board?.column_groups || []);
        if (this.state.board && !this.state.board.is_default && this.saved.swimlane !== this.props.swimlane) {
            this.props.onSwimlane(this.saved.swimlane);
        }
    }

    async manageBoards() {
        const action = await this.orm.call("project.project", "action_agile_manage_boards", [[this.props.projectId]]);
        await this.actionService.doAction(action, { onClose: () => this.reloadBoardOptions() });
    }

    async copyBoard() {
        try {
            const copy = await this.orm.call("project.project", "agile_board_copy", [[this.props.projectId]], {
                board_id: this.state.board?.id || false,
            });
            await this.orm.call("project.project", "agile_board_switch", [[this.props.projectId]], { board_id: copy.id });
            await this.reloadBoardOptions();
            this.state.announce = _t("Copied to %(name)s.", { name: copy.name });
        } catch (error) {
            this.state.announce = error?.data?.message || _t("Could not copy the board. Try again.");
        }
    }

    // ---- the board query (R-1101): a saved query the board starts limited to ----

    queryItems() {
        return this.searchModel.getSearchItems((item) => item.type === "filter" && item.agileBoardQuery);
    }

    get queryOn() {
        return this.queryItems().some((item) => item.isActive);
    }

    /** Show the board's saved query as one search filter, switched on; a new choice replaces the old one. */
    applyQuery() {
        for (const item of this.queryItems()) {
            if (item.isActive) {
                this.searchModel.toggleSearchItem(item.id);
            }
        }
        const query = this.state.query;
        if (query?.domain) {
            this.searchModel.createNewFilters([
                {
                    description: _t("Query: %(name)s", { name: query.name }),
                    domain: JSON.stringify(query.domain),
                    agileBoardQuery: query.id,
                },
            ]);
        }
    }

    toggleQuery() {
        const item = this.queryItems().at(-1);
        if (item) {
            this.searchModel.toggleSearchItem(item.id);
        }
    }

    async onQueryPick(ev) {
        try {
            this.state.query = await this.orm.call("project.project", "agile_set_board_query", [[this.props.projectId]], {
                filter_id: Number(ev.target.value) || false,
            });
            this.applyQuery();
            this.state.announce = this.state.query
                ? _t("The board is limited to %(name)s.", { name: this.state.query.name })
                : _t("The board shows every issue again.");
        } catch (error) {
            this.state.announce = error?.data?.message || _t("Could not change the board query. Try again.");
        }
    }

    // ---- changing it ----

    pickedSprints() {
        return this.activeKeys()
            .filter((key) => key.startsWith("sprint:"))
            .map((key) => Number(key.split(":")[1]));
    }

    sprintSummary() {
        const picked = this.state.sprints.filter((sprint) => this.pickedSprints().includes(sprint.id));
        if (!picked.length) {
            return _t("All active sprints");
        }
        return picked.length === 1 ? picked[0].name : _t("%(count)s sprints", { count: picked.length });
    }

    toggleSprint(id) {
        const current = this.pickedSprints();
        this.setSprints(current.includes(id) ? current.filter((value) => value !== id) : [...current, id]);
    }

    /** The sprint picks are one search filter, so the board shows the issues of any ticked sprint. */
    setSprints(ids) {
        const keys = ids.map((id) => `sprint:${id}`);
        for (const item of this.boardFilters()) {
            if (item.isActive && (item.agileBoardKeys || [item.agileBoardKey]).some((key) => key.startsWith("sprint:"))) {
                this.searchModel.toggleSearchItem(item.id);
            }
        }
        if (!ids.length) {
            return;
        }
        const names = this.state.sprints.filter((sprint) => ids.includes(sprint.id)).map((sprint) => sprint.name);
        const existing = this.boardFilters().find(
            (item) => item.agileBoardKeys && this.keyString(item.agileBoardKeys) === this.keyString(keys)
        );
        if (existing) {
            this.searchModel.toggleSearchItem(existing.id);
            return;
        }
        this.searchModel.createNewFilters([
            {
                description: _t("Sprint: %(names)s", { names: names.join(", ") }),
                domain: JSON.stringify([["sprint_id", "in", ids]]),
                agileBoardKeys: keys,
            },
        ]);
    }

    setKey(key, on) {
        if (key.startsWith("sprint:")) {
            const id = Number(key.split(":")[1]);
            const rest = this.pickedSprints().filter((value) => value !== id);
            this.setSprints(on ? [...rest, id] : rest);
            return;
        }
        if (key in NAMED_FILTERS) {
            const item = this.namedFilter(NAMED_FILTERS[key]);
            if (item && item.isActive !== on) {
                this.searchModel.toggleSearchItem(item.id);
            }
            return;
        }
        const [kind] = key.split(":");
        // One type and one epic at a time.
        for (const item of this.boardFilters()) {
            if (item.isActive && item.agileBoardKey?.startsWith(kind + ":") && item.agileBoardKey !== key) {
                this.searchModel.toggleSearchItem(item.id);
            }
        }
        const existing = this.boardFilters().find((item) => item.agileBoardKey === key);
        if (existing) {
            if (existing.isActive !== on) {
                this.searchModel.toggleSearchItem(existing.id);
            }
            return;
        }
        if (on) {
            this.createFilter(key);
        }
    }

    createFilter(key) {
        const [kind, id] = key.split(":");
        const item = this.listFor(kind).find((entry) => String(entry.id) === id);
        if (!item) {
            return;
        }
        const field = { type: "agile_task_type_id", epic: "parent_id" }[kind];
        const label = {
            type: _t("Type: %(name)s", { name: item.name }),
            epic: _t("Epic: %(name)s", { name: item.name }),
        }[kind];
        this.searchModel.createNewFilters([
            { description: label, domain: `[("${field}", "=", ${item.id})]`, agileBoardKey: key },
        ]);
    }

    toggleChip(key) {
        this.setKey(key, !this.isOn(key));
    }

    onPick(kind, ev) {
        const id = ev.target.value;
        if (id) {
            this.setKey(`${kind}:${id}`, true);
        } else {
            for (const item of this.boardFilters()) {
                if (item.isActive && item.agileBoardKey?.startsWith(kind + ":")) {
                    this.searchModel.toggleSearchItem(item.id);
                }
            }
        }
    }

    // ---- saved views (S-933): named combinations of the chips, pick lists and swimlane ----

    /** Switch everything to a saved view: clear what is on, then set what the view holds. */
    applyView(view) {
        for (const key of Object.keys(NAMED_FILTERS)) {
            if (this.isOn(key)) {
                this.setKey(key, false);
            }
        }
        for (const item of this.boardFilters()) {
            if (item.isActive) {
                this.searchModel.toggleSearchItem(item.id);
            }
        }
        const keys = view.filters.filter((key) => this.knownKey(key));
        for (const key of keys.filter((key) => !key.startsWith("sprint:"))) {
            this.setKey(key, true);
        }
        this.setSprints(keys.filter((key) => key.startsWith("sprint:")).map((key) => Number(key.split(":")[1])));
        this.pickSwimlane(view.swimlane);
        this.state.announce = _t("Showing the view %(name)s.", { name: view.name });
    }

    startSaveView() {
        this.state.saving = true;
        this.state.viewName = "";
        this.state.viewError = "";
    }

    async saveView() {
        const name = this.state.viewName.trim();
        if (!name) {
            this.state.viewError = _t("Give the view a name.");
            return;
        }
        try {
            this.state.views = await this.orm.call("project.project", "agile_save_board_view", [[this.props.projectId]], {
                name,
                filters: this.activeKeys(),
                swimlane: this.props.swimlane,
            });
            this.state.saving = false;
            this.state.announce = _t("Saved the view %(name)s.", { name });
        } catch (error) {
            this.state.viewError = error?.data?.message || _t("Could not save the view. Try again.");
        }
    }

    async deleteView(view) {
        try {
            this.state.views = await this.orm.call("project.project", "agile_delete_board_view", [[this.props.projectId]], {
                name: view.name,
            });
            this.state.announce = _t("Deleted the view %(name)s.", { name: view.name });
        } catch {
            this.state.announce = _t("Could not delete the view. Try again.");
        }
    }

    /** The saved filter the swimlane names, for the picker ("" when it is another kind). */
    get laneFilterValue() {
        return String(this.props.swimlane).startsWith("filter:") ? this.props.swimlane : "";
    }

    onLaneSelect(ev) {
        this.pickSwimlane(ev.target.value);
    }

    pickSwimlane(value) {
        if (value === this.props.swimlane) {
            return;
        }
        this.props.onSwimlane(value);
        this.save({ swimlane: value });
    }

    async save({ swimlane, filters }) {
        if (filters) {
            this.savedKey = this.keyString(filters);
        }
        try {
            await this.orm.call("project.project", "agile_save_board_options", [[this.props.projectId]], {
                swimlane,
                filters,
            });
        } catch {
            // Saving is a convenience; the board keeps working with what is on screen.
        }
    }
}
