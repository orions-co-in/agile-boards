import { onWillRender, useRef, useState } from "@odoo/owl";
import { useSortable } from "@web/core/utils/sortable_owl";
import { useService } from "@web/core/utils/hooks";
import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation";
import { KanbanRecord } from "@web/views/kanban/kanban_record";
import { ProjectTaskKanbanRenderer } from "@project/views/project_task_kanban/project_task_kanban_renderer";
import { AgileColumnHeader } from "./agile_column_header";
import {
    columnFacts,
    cellWip,
    lanesKey,
    overLimitMessage,
    readClosedLanes,
    wipState,
    writeClosedLanes,
} from "./board_helpers";
import {
    edgeMessage,
    movedMessage,
    neighbourGroup,
    otherRowMessage,
    reasonOf,
    refusedMessage,
} from "./board_moves";

/** The stage id of a card, whether the model gives an id, a pair or an object. */
function stageOf(record) {
    const value = record?.data.stage_id;
    return Array.isArray(value) ? value[0] : (value?.id ?? value);
}

const LANE_FIELD = {
    assignee: "agile_lane_assignee",
    epic: "agile_lane_epic",
    priority: "agile_lane_priority",
    component: "agile_lane_component",
    label: "agile_lane_label",
};

/** The saved filter id a swimlane names ("filter:12"), or null for the other kinds. */
export function laneFilterId(swimlane) {
    const match = /^filter:(\d+)$/.exec(swimlane || "");
    return match ? Number(match[1]) : null;
}

/** What an issue with no value sits under, per kind of swimlane. */
export function emptyLaneLabel(swimlane) {
    return (
        {
            epic: _t("No epic"),
            priority: _t("No priority"),
            component: _t("No component"),
            label: _t("No label"),
        }[swimlane] || (laneFilterId(swimlane) ? _t("Everything else") : _t("Unassigned"))
    );
}

/** Group issues into swimlane rows; lanes with a name sort first, "no one" / "no epic" last. */
export function buildLanes(groups, swimlane, emptyLabel, filterLane = null) {
    const field = LANE_FIELD[swimlane];
    const lanes = new Map();
    for (const group of groups) {
        for (const record of group.list.records) {
            // A saved-filter lane has two rows: what the filter matches, and everything else.
            const label = filterLane ? (filterLane.ids.has(record.resId) ? filterLane.name : "") : record.data[field] || "";
            if (!lanes.has(label)) {
                lanes.set(label, {
                    key: label,
                    label: label || emptyLabel,
                    empty: !label,
                    count: 0,
                    points: 0,
                    cells: groups.map((cellGroup) => ({ group: cellGroup, records: [] })),
                });
            }
            const lane = lanes.get(label);
            lane.cells[groups.indexOf(group)].records.push(record);
            lane.count += 1;
            if (record.data.story_points_estimated) {
                lane.points += record.data.story_points || 0;
            }
        }
    }
    return [...lanes.values()].sort(
        (a, b) => a.empty - b.empty || a.label.localeCompare(b.label, undefined, { numeric: true })
    );
}

/**
 * Merged columns (R-1111): one unit per column of the board, in the board's order. A unit stands in
 * for its landing status (same id and value) so a drop on it moves a card there, and it holds the
 * cards of all its statuses. Statuses the board does not list are not shown.
 */
export function mergeColumns(groups, columnGroups) {
    const byStage = new Map(groups.map((group) => [Array.isArray(group.value) ? group.value[0] : group.value, group]));
    const units = [];
    for (const column of columnGroups) {
        const members = column.stage_ids.map((id) => byStage.get(id)).filter(Boolean);
        if (!members.length) {
            continue;
        }
        const landing = members.find((group) => (Array.isArray(group.value) ? group.value[0] : group.value) === column.landing_id) || members[0];
        units.push({
            id: landing.id,
            value: landing.value,
            displayName: column.name,
            isFolded: false,
            merged: members.length > 1,
            members,
            list: { records: members.flatMap((group) => group.list.records) },
        });
    }
    return units;
}

/** A card picked for the bulk bar shows a ring and a tick (S-931). */
export class AgileKanbanRecord extends KanbanRecord {
    setup() {
        super.setup();
        // Watch the shared selection, so this card redraws when it is picked or dropped.
        this.pick = this.env.agileSelect ? useState(this.env.agileSelect) : null;
    }

    getRecordClasses() {
        const classes = super.getRecordClasses();
        const picked = this.pick?.on && this.pick.ids.includes(this.props.record.resId);
        if (!picked) {
            return classes;
        }
        return Array.isArray(classes) ? [...classes, "o_ag_card_selected"] : `${classes} o_ag_card_selected`;
    }
}

export class AgileBoardKanbanRenderer extends ProjectTaskKanbanRenderer {
    static template = "agile_community.BoardKanbanRenderer";
    static components = { ...ProjectTaskKanbanRenderer.components, KanbanRecord: AgileKanbanRecord, KanbanHeader: AgileColumnHeader };
    static props = [...ProjectTaskKanbanRenderer.props, "swimlane?"];

    setup() {
        super.setup();
        // Redraw when the board's columns or merged columns change (the bar sets them after it loads).
        this.boardState = this.env.agileBoard ? useState(this.env.agileBoard) : null;
        this.laneState = useState({ collapsed: {}, swimlane: null });
        this.laneFilter = useState({ id: null, name: "", ids: null });
        // Phones show one column at a time; the Move-to sheet lists what the person may do.
        this.tabState = useState({ id: null });
        this.sheet = useState({ recordId: null, title: "", moves: [], loading: false, groupId: null });
        this.sheetRef = useRef("sheet");
        onWillRender(() => {
            this.syncClosedLanes();
            const filterId = laneFilterId(this.props.swimlane);
            if (filterId && this.laneFilter.id !== filterId) {
                this.loadLaneFilter(filterId);
            }
        });
        this.orm = useService("orm");
        this.notification = useService("notification");
        // Swimlane cards drag sideways to change status; a drop on another row is refused.
        let draggedId = null;
        let fromGroupId = null;
        useSortable({
            enable: () => this.swimlaneMode && this.canMoveRecords,
            ref: this.rootRef,
            elements: ".o_ag_lane_item",
            ignore: ".dropdown,select",
            groups: () => this.swimlaneMode && ".o_ag_lane_cell",
            connectGroups: true,
            cursor: "move",
            placeholderClasses: ["visible", "opacity-50", "my-2"],
            onDragStart: ({ element, group }) => {
                draggedId = element.dataset.id;
                fromGroupId = group?.dataset.id;
            },
            onDrop: ({ parent, group }) => this.dropOnLane(draggedId, fromGroupId, parent, group),
        });
    }

    /** Sideways drop inside a row moves the card; another row is refused and the card stays. */
    async dropOnLane(recordId, fromGroupId, targetCell, originCell) {
        const record = this.props.list.records.find((r) => r.id === recordId);
        if (!record || !targetCell) {
            return;
        }
        // Cells of one column share a group id across rows, so the row is checked first.
        if (targetCell.dataset.lane !== originCell?.dataset.lane) {
            this.notification.add(
                otherRowMessage(record.data.issue_key, originCell?.dataset.lane, this.props.swimlane),
                { type: "warning" }
            );
            return;
        }
        if (targetCell.dataset.id === fromGroupId) {
            return;
        }
        // A merged column's cell carries its landing status's id; the card leaves the status it is really in.
        const current = this.props.list.groups.find((group) => group.list.records.includes(record));
        await this.moveCard(record, current?.id || fromGroupId, targetCell.dataset.id);
    }

    /**
     * Move a card to another column with the workflow rules of the server.
     * Returns true when it moved; a refusal is worded and the card snaps back.
     */
    async moveCard(record, fromGroupId, toGroupId, { announce = false } = {}) {
        this.toggleProcessing(record.id, true);
        try {
            await this.props.list.moveRecord(record.id, fromGroupId, null, toGroupId);
        } catch (error) {
            this.notification.add(refusedMessage(record.data.issue_key, reasonOf(error)), { type: "danger" });
            return false;
        } finally {
            this.toggleProcessing(record.id, false);
        }
        const group = this.props.list.groups.find((g) => g.list.records.includes(record));
        if (announce) {
            this.notification.add(movedMessage(record.data.issue_key, group?.displayName || ""), { type: "info" });
        }
        await this.warnWhenOverLimit(record, fromGroupId);
        return true;
    }

    /** Alt+Left and Alt+Right move the focused card one column, with the same rules as a drag. */
    async onCardKeydown(ev) {
        if (!ev.altKey || !["ArrowLeft", "ArrowRight"].includes(ev.key) || !this.props.list.isGrouped) {
            return;
        }
        const card = ev.target.closest(".o_kanban_record");
        const holder = card?.closest(".o_ag_lane_item, [data-id]") || card;
        const record = this.props.list.records.find((r) => r.id === holder?.dataset.id);
        if (!record || !this.canMoveRecords) {
            return;
        }
        ev.preventDefault();
        const direction = ev.key === "ArrowLeft" ? -1 : 1;
        const from = this.props.list.groups.find((g) => g.list.records.includes(record));
        const to = neighbourGroup(this.props.list.groups, from, direction);
        if (!to) {
            this.notification.add(edgeMessage(record.data.issue_key, direction), { type: "info" });
            return;
        }
        const key = record.data.issue_key;
        if (await this.moveCard(record, from.id, to.id, { announce: true })) {
            this.focusCard(key);
        }
    }

    focusCard(key) {
        setTimeout(() => {
            [...this.rootRef.el.querySelectorAll(".o_kanban_record")]
                .find((el) => el.innerText.includes(key))
                ?.focus();
        }, 0);
    }

    /**
     * A drop into a column that ends up over its WIP limit still works; the message says so
     * and offers Undo (WIP is a warning, not a cap).
     */
    async sortRecordDrop(dataRecordId, dataGroupId, params) {
        const record = this.props.list.records.find((r) => r.id === dataRecordId);
        const fromStage = stageOf(record);
        try {
            await super.sortRecordDrop(dataRecordId, dataGroupId, params);
        } catch (error) {
            // A column the workflow forbids: say why in a message, not an Invalid Operation dialog (NU-10).
            const reason = reasonOf(error);
            if (!reason) {
                throw error;
            }
            this.notification.add(refusedMessage(record?.data.issue_key || "", reason), { type: "danger" });
            return;
        }
        const stageNow = stageOf(record);
        if (record && stageNow !== fromStage) {
            await this.warnWhenOverLimit(record, dataGroupId);
        }
    }

    async warnWhenOverLimit(record, fromGroupId) {
        const projectId = this.props.list.context.default_project_id;
        let stages;
        try {
            stages = (await this.orm.call("project.project", "agile_board_wip", [[projectId]])).stages;
        } catch {
            return;
        }
        const stageId = stageOf(record);
        const entry = stages.find((stage) => stage.stage_id === stageId);
        const wip = entry && wipState(entry.limit, entry.current);
        if (wip?.kind !== "over") {
            return;
        }
        const group = this.props.list.groups.find((g) => g.list.records.includes(record));
        this.notification.add(overLimitMessage(record.data.issue_key, group?.displayName || "", wip), {
            type: "warning",
            buttons: [
                {
                    name: _t("Undo"),
                    onClick: () => this.props.list.moveRecord(record.id, group?.id, null, fromGroupId),
                },
            ],
        });
    }

    get phoneMode() {
        return Boolean(this.env.isSmall && this.props.list.isGrouped);
    }

    /** The columns the current board shows (R-1107); a board with none chosen shows them all. */
    get shownGroups() {
        const columns = this.boardState?.columns;
        const groups = this.props.list.groups;
        if (!columns?.length) {
            return groups;
        }
        return groups.filter((group) => columns.includes(Array.isArray(group.value) ? group.value[0] : group.value));
    }

    get activeTabId() {
        const groups = this.shownGroups;
        return groups.some((group) => group.id === this.tabState.id) ? this.tabState.id : groups[0]?.id;
    }

    get phoneTabs() {
        if (!this.phoneMode) {
            return null;
        }
        return this.shownGroups.map((group) => ({
            id: group.id,
            name: group.displayName,
            count: group.list.records.length + this.getGroupUnloadedCount(group),
            active: group.id === this.activeTabId,
            wip: this.columnFacts(group).wip,
        }));
    }

    selectTab(id) {
        this.tabState.id = id;
    }

    getGroupsOrRecords() {
        const shown = new Set(this.shownGroups.map((group) => group.id));
        const items = super.getGroupsOrRecords().filter((item) => !item.group || shown.has(item.group.id));
        return this.phoneMode ? items.filter((item) => item.group?.id === this.activeTabId) : items;
    }

    /** "Move to..." on a card opens a sheet of the moves the server allows this person. */
    async onMoveToClick(ev) {
        const link = ev.target.closest(".o_ag_move_to");
        if (!link) {
            return;
        }
        ev.preventDefault();
        const holder = link.closest("[data-id]");
        const record = this.props.list.records.find((r) => r.id === holder?.dataset.id);
        if (!record || !this.canMoveRecords) {
            return;
        }
        const group = this.props.list.groups.find((g) => g.list.records.includes(record));
        this.sheetTrigger = link;
        Object.assign(this.sheet, {
            recordId: record.id,
            title: _t("Move %(key)s", { key: record.data.issue_key }),
            moves: [],
            loading: true,
            groupId: group?.id,
        });
        let moves = [];
        try {
            moves = await this.orm.call("project.task", "agile_allowed_moves", [[record.resId]]);
        } catch {
            moves = [];
        }
        this.sheet.moves = moves;
        this.sheet.loading = false;
        setTimeout(() => this.sheetRef.el?.focus(), 0);
    }

    closeSheet() {
        this.sheet.recordId = null;
        // Give focus back to the button that opened the sheet, as long as it is still on the page.
        const trigger = this.sheetTrigger;
        this.sheetTrigger = null;
        setTimeout(() => {
            if (trigger?.isConnected) {
                trigger.focus();
            }
        }, 0);
    }

    onSheetKeydown(ev) {
        if (ev.key === "Escape") {
            ev.stopPropagation();
            this.closeSheet();
        }
    }

    async chooseMove(move) {
        const record = this.props.list.records.find((r) => r.id === this.sheet.recordId);
        const target = this.props.list.groups.find((group) => group.value === move.stage_id);
        const fromId = this.sheet.groupId;
        this.closeSheet();
        if (!record || !target) {
            return;
        }
        await this.moveCard(record, fromId, target.id, { announce: true });
    }

    get swimlaneMode() {
        return (
            !this.env.isSmall &&
            this.props.list.isGrouped &&
            (Boolean(LANE_FIELD[this.props.swimlane]) || Boolean(this.filterLane) || this.mergedMode)
        );
    }

    /** R-1111: a board with merged columns uses the grid, where a column can hold several statuses. */
    get mergedMode() {
        return Boolean(this.boardState?.columnGroups?.length) && !this.env.isSmall && this.props.list.isGrouped;
    }

    /** Without a swimlane (merged columns only) the grid has one row and no row title. */
    get singleLane() {
        return this.mergedMode && !LANE_FIELD[this.props.swimlane] && !this.filterLane;
    }

    /** The saved filter behind a "filter:<id>" swimlane, once its issues are known. */
    get filterLane() {
        const id = laneFilterId(this.props.swimlane);
        return id && this.laneFilter.id === id && this.laneFilter.ids ? this.laneFilter : null;
    }

    async loadLaneFilter(id) {
        this.laneFilter.id = id;
        this.laneFilter.ids = null;
        try {
            const result = await this.orm.call("project.project", "agile_board_filter_ids", [
                [this.props.list.context.default_project_id],
                id,
            ]);
            if (this.laneFilter.id === id) {
                this.laneFilter.name = result.name;
                this.laneFilter.ids = new Set(result.ids);
            }
        } catch {
            this.notification.add(_t("That saved filter could not be read. Choose another swimlane."), { type: "warning" });
        }
    }

    get laneGroups() {
        const groups = this.shownGroups.filter((group) => !group.isFolded);
        return this.mergedMode ? mergeColumns(groups, this.boardState.columnGroups) : groups;
    }

    /** Cards of a column, counting those not loaded yet; a merged column adds up its statuses. */
    unitCount(unit) {
        const groups = unit.members || [unit];
        return groups.reduce((sum, group) => sum + group.list.records.length + this.getGroupUnloadedCount(group), 0);
    }

    /** The status a card is really in, for the chip a merged column shows on it. */
    statusName(record) {
        return this.props.list.groups.find((group) => group.list.records.includes(record))?.displayName || "";
    }

    get lanes() {
        return buildLanes(this.laneGroups, this.props.swimlane, emptyLaneLabel(this.props.swimlane), this.filterLane);
    }

    /** WIP badge and blocked count per shared column heading. */
    columnFacts(group) {
        return columnFacts(group, this.boardState?.wip, this.swimlaneMode);
    }

    /** WIP badge for one swimlane cell when its stage counts per row. */
    cellWip(cell) {
        if (cell.group.merged) {
            return null; // per-row limits are not shown inside merged columns
        }
        return cellWip(cell.group, this.boardState?.wip, cell.records.length);
    }

    get laneStyle() {
        return `grid-template-columns: repeat(${this.laneGroups.length}, minmax(13rem, 1fr));`;
    }

    get hiddenCount() {
        return this.laneGroups.reduce(
            (sum, unit) => sum + (unit.members || [unit]).reduce((inner, group) => inner + this.getGroupUnloadedCount(group), 0),
            0
        );
    }

    get lanesStorageKey() {
        return lanesKey(this.props.list.context.default_project_id, this.props.swimlane);
    }

    /** Folded rows come back the way they were left, per project and kind of swimlane. */
    syncClosedLanes() {
        if (this.laneState.swimlane !== this.props.swimlane) {
            this.laneState.swimlane = this.props.swimlane;
            this.laneState.collapsed = Object.fromEntries(
                readClosedLanes(browser.localStorage, this.lanesStorageKey).map((key) => [key, true])
            );
        }
    }

    isCollapsed(lane) {
        return Boolean(this.laneState.collapsed[lane.key]);
    }

    toggleLane(lane) {
        this.laneState.collapsed[lane.key] = !this.isCollapsed(lane);
        const closed = Object.keys(this.laneState.collapsed).filter((key) => this.laneState.collapsed[key]);
        writeClosedLanes(browser.localStorage, this.lanesStorageKey, closed);
    }
}
