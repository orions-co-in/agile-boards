import { onMounted, onPatched, onWillStart, onWillUnmount, onWillUpdateProps, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { browser } from "@web/core/browser/browser";
import { usePopover } from "@web/core/popover/popover_hook";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { AgileInlineEditor } from "./agile_inline_editor";
import { AgileMoveToDialog } from "./agile_move_dialog";
import { AgileRowSheet } from "./agile_row_sheet";
import { AgileQuickCreate } from "./agile_quick_create";
import { AgileBulkBar } from "@agile_community/bulk/agile_bulk_bar";
import { boundaryMessage, moveMessage, rankMessage, refusalMessage } from "./backlog_moves";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";
import { ListRenderer } from "@web/views/list/list_renderer";
import {
    backlogText,
    dateRange,
    epicProgress,
    planChip,
    pointsText,
    ribbonLabel,
    ribbonSegments,
    stateLabel,
    unestimatedText,
} from "./backlog_helpers";

const HIDE_COMPLETED_FILTER = "agile_hide_completed";
const EPICS_OPEN_KEY = "agile_backlog_epics_open";
// Secondary columns that drop out on phones; the issue form still shows them.
// Cells that open a small editor on click (spec section 12).
const EDITABLE_COLUMNS = ["story_points", "user_ids", "agile_task_type_id"];
const PHONE_HIDDEN_COLUMNS = ["agile_task_type_id", "parent_id", "agile_is_blocked", "agile_blocked_by_text", "agile_lock_text"];

/** Group headers for the backlog: sprint state, dates, goal, capacity ribbon and plan actions. */
export class AgileBacklogRenderer extends ListRenderer {
    static template = "agile_community.BacklogListRenderer";
    static rowsTemplate = "agile_community.BacklogRows";
    static components = { ...ListRenderer.components, AgileQuickCreate, Dropdown, AgileBulkBar };
    static groupRowTemplate = "agile_community.BacklogGroupRow";

    setup() {
        super.setup();
        this.action = useService("action");
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.dialog = useService("dialog");
        this.announcer = useState({ text: "" });
        this.onBacklogKeydown = this.onBacklogKeydown.bind(this);
        this.onBacklogClick = this.onBacklogClick.bind(this);
        this.editTarget = null;
        this.editor = usePopover(AgileInlineEditor, {
            position: "bottom-start",
            popoverClass: "o_ag_inline_popover",
            onClose: () => this.editTarget?.focus?.(),
        });
        this.quick = useState({ typeId: null });
        this.refocusQuick = null;
        this.refocusRecord = null;
        // Capture phase, so Alt+arrows and "m" are handled before the native cell navigation.
        onMounted(() => {
            this.reopenAutoFoldedGroups();
            this.rootRef.el.addEventListener("keydown", this.onBacklogKeydown, true);
            this.rootRef.el.addEventListener("click", this.onBacklogClick, true);
            this.syncEditable();
        });
        onPatched(() => {
            this.syncEditable();
            this.reopenAutoFoldedGroups();
            this.restoreRowFocus();
            if (this.refocusQuick !== null) {
                this.rootRef.el
                    .querySelector(`.o_ag_quick_input[data-group-key="${this.refocusQuick}"]`)
                    ?.focus();
                this.refocusQuick = null;
            }
        });
        onWillUnmount(() => {
            this.rootRef.el?.removeEventListener("keydown", this.onBacklogKeydown, true);
            this.rootRef.el?.removeEventListener("click", this.onBacklogClick, true);
        });
        this.info = useState({ data: null, error: false });
        this.epics = useState({ data: null, open: this.readEpicsOpen() });
        this.infoKey = null;
        this.foldedByUser = new Set();
        this.emptiedGroups = new Set();
        onWillStart(() => this.loadInfo());
        onWillUpdateProps((nextProps) => {
            // Reload the header numbers when the visible groups change, without blocking the render.
            this.loadInfo(nextProps);
        });
    }

    toggleGroup(group) {
        // Remember groups the person folded themselves; others are reopened when they get rows.
        const key = String(group.value);
        if (group.isFolded) {
            this.foldedByUser.delete(key);
        } else {
            this.foldedByUser.add(key);
        }
        return super.toggleGroup(group);
    }

    /**
     * A filter (an epic, say) that empties a sprint folds it, and Odoo keeps it folded when
     * rows come back. Open such groups again unless the person folded them on purpose.
     * Groups Odoo folded on load (a huge backlog) were never empty, so they stay as they are.
     */
    reopenAutoFoldedGroups() {
        for (const group of this.props.list.groups || []) {
            const key = String(group.value);
            if (!group.count) {
                this.emptiedGroups.add(key);
            } else if (
                (this.emptiedGroups.delete(key) || !group.value) &&
                group.isFolded &&
                !this.foldedByUser.has(key)
            ) {
                // Odoo folds the group "no sprint" (our Backlog) on load; that hid the add-issue row (NU-28).
                group.toggle();
            }
        }
    }

    get projectId() {
        const context = this.props.list.context || {};
        return context.default_project_id || context.active_id;
    }

    groupsKey(props = this.props) {
        const groups = props.list.groups || [];
        return JSON.stringify(groups.map((group) => [group.value, group.count]));
    }

    async loadInfo(props = this.props) {
        const key = this.groupsKey(props);
        if (!this.projectId || key === this.infoKey) {
            return;
        }
        this.infoKey = key;
        try {
            const [info, epics] = await Promise.all([
                this.orm.call("project.project", "agile_backlog_sprints", [[this.projectId]]),
                // The epic panel is optional: if it cannot load, the rows and headers still work.
                this.orm.call("project.project", "agile_backlog_epics", [[this.projectId]]).catch(() => null),
            ]);
            this.info.data = info;
            this.epics.data = epics;
            this.info.error = false;
        } catch {
            this.info.error = true;
        }
    }

    retryInfo() {
        this.infoKey = null;
        return this.loadInfo();
    }

    getActiveColumns() {
        const columns = super.getActiveColumns();
        return this.uiService.isSmall
            ? columns.filter((column) => !PHONE_HIDDEN_COLUMNS.includes(column.name))
            : columns;
    }

    // The sprint header already states the points, so the native sum column stays empty.
    getFirstAggregateIndex(group) {
        return this.isSprintGroup(group) ? -1 : super.getFirstAggregateIndex(group);
    }

    getLastAggregateIndex(group) {
        return this.isSprintGroup(group) ? -1 : super.getLastAggregateIndex(group);
    }

    /** An empty project has no groups, so the Backlog needs its own empty state and quick add. */
    get emptyBacklog() {
        const list = this.props.list;
        return Boolean(this.info.data) && list.isGrouped && !(list.groups || []).length;
    }

    get emptyGroup() {
        const group = { value: false, displayName: _t("Backlog"), groupByField: { name: "sprint_id" } };
        return this.quickAllowed(group) ? group : null;
    }

    isSprintGroup(group) {
        return group?.groupByField?.name === "sprint_id";
    }

    /**
     * Planned sprints the person may run, with their next step. The sprint headers carry the same
     * buttons, but on a phone they sit below the active sprint's rows; this strip keeps them in view (Q-601).
     */
    get planActions() {
        return (this.info.data?.sprints || [])
            .filter((sprint) => sprint.can_manage && planChip(sprint))
            .map((sprint) => ({ sprint, chip: planChip(sprint) }));
    }

    sprintFor(group) {
        return this.info.data?.sprints.find((sprint) => sprint.id === group.value) || null;
    }

    isBacklogGroup(group) {
        return this.isSprintGroup(group) && !group.value;
    }

    groupName(group) {
        return this.isBacklogGroup(group) ? _t("Backlog") : group.displayName;
    }

    stateLabel = stateLabel;
    dates = dateRange;
    pointsText(sprint) {
        return pointsText(sprint, this.info.data?.estimate_unit);
    }
    ribbonSegments = ribbonSegments;
    ribbonLabel(sprint) {
        return ribbonLabel(sprint, this.info.data?.estimate_unit);
    }
    unestimatedText = unestimatedText;
    planChip = planChip;

    backlogText() {
        return backlogText(this.info.data?.backlog);
    }

    // ---- Moving issues: drag, keyboard rank and the Move-to menu (spec section 12) ----

    groupById(groupId) {
        return this.props.list.groups?.find((group) => group.id === groupId);
    }

    isCompletedGroup(group) {
        return this.sprintFor(group)?.state === "done";
    }

    location(group) {
        return { name: this.groupName(group), sprint: this.sprintFor(group) };
    }

    /** Where a record sits before a move, so the result can be worded and undone. */
    snapshotRecord(recordId, groupId) {
        const group = this.groupById(groupId);
        const records = group?.list.records || [];
        const index = records.findIndex((record) => record.id === recordId);
        if (index < 0) {
            return null;
        }
        const record = records[index];
        return {
            recordId,
            resId: record.resId,
            groupId,
            index,
            previousId: records[index - 1]?.id ?? null,
            key: record.data.issue_key || record.data.name,
            from: this.location(group),
        };
    }

    announce(message) {
        this.announcer.text = message;
    }

    say(message, { type = "info", undo } = {}) {
        this.announce(message);
        this.notification.add(message, {
            type,
            buttons: undo ? [{ name: _t("Undo"), onClick: undo }] : [],
        });
    }

    reasonFor(error) {
        return error?.data?.message || error?.message || "";
    }

    /** The server said no: put the list back and say why in plain words. */
    async refuseMove(snapshot, error) {
        this.say(refusalMessage(snapshot.key, this.reasonFor(error)), { type: "danger" });
        await this.props.list.model.load();
    }

    refreshInfo() {
        this.infoKey = null;
        // The sidebar's Backlog and Board counts change with the issues (NU-29).
        this.env.bus.trigger("AGILE:SIDEBAR-REFRESH");
        return this.loadInfo();
    }

    /** Word the result of a finished move, offer Undo and refresh the sprint headers. */
    async finishMove(snapshot, targetGroupId) {
        const targetGroup = this.groupById(targetGroupId);
        const sameGroup = targetGroupId === snapshot.groupId;
        let message;
        if (sameGroup) {
            const index = targetGroup.list.records.findIndex((r) => r.id === snapshot.recordId);
            if (index === snapshot.index) {
                return;
            }
            message = rankMessage(snapshot.key, index + 1, targetGroup.count, this.groupName(targetGroup));
        } else {
            message = moveMessage(snapshot.key, snapshot.from, this.location(targetGroup));
        }
        const undo = () => this.undoMove(snapshot, targetGroupId);
        this.say(message, { undo });
        await this.refreshInfo();
    }

    async undoMove(snapshot, currentGroupId) {
        try {
            await this.props.list.moveRecord(
                snapshot.recordId,
                currentGroupId,
                snapshot.previousId,
                snapshot.groupId
            );
            this.announce(_t("Move undone."));
            await this.refreshInfo();
        } catch (error) {
            this.say(_t("Could not undo: %(reason)s", { reason: this.reasonFor(error) }), { type: "danger" });
            await this.props.list.model.load();
        }
    }

    async sortDrop(dataRowId, dataGroupId, params) {
        const snapshot = dataGroupId ? this.snapshotRecord(dataRowId, dataGroupId) : null;
        if (!snapshot) {
            return super.sortDrop(dataRowId, dataGroupId, params);
        }
        const targetGroupId = params.previous?.dataset.groupId || dataGroupId;
        const targetGroup = this.groupById(targetGroupId);
        if (targetGroup && this.isCompletedGroup(targetGroup)) {
            this.say(_t("Completed sprints cannot take issues here. Use the sprint's Correct action."), {
                type: "warning",
            });
            await this.props.list.model.load();
            return;
        }
        try {
            await super.sortDrop(dataRowId, dataGroupId, params);
        } catch (error) {
            await this.refuseMove(snapshot, error);
            return;
        }
        await this.finishMove(snapshot, targetGroupId);
    }

    getRowClass(record) {
        const base = super.getRowClass(record);
        const sprintId = record.data.sprint_id?.id ?? record.data.sprint_id?.[0];
        const sprint = this.info.data?.sprints.find((item) => item.id === sprintId);
        if (sprint?.state !== "done") {
            return base;
        }
        // Completed sprints keep their history: no handle, no drag.
        return base.split(" ").filter((name) => name !== "o_row_draggable").concat("o_ag_row_locked").join(" ");
    }

    /** Put the focus back on a row after a move re-renders the list. */
    focusRecordRow(recordId) {
        this.refocusRecord = recordId;
        clearTimeout(this.refocusTimer);
        // The row is rebuilt by the next render; keep trying until the timer ends.
        this.refocusTimer = setTimeout(() => {
            this.restoreRowFocus();
            this.refocusRecord = null;
        }, 0);
    }

    restoreRowFocus() {
        if (this.refocusRecord === null) {
            return;
        }
        this.rootRef.el
            ?.querySelector(`tr.o_data_row[data-id="${this.refocusRecord}"] td.o_data_cell`)
            ?.focus();
    }

    onBacklogKeydown(ev) {
        const row = ev.target.closest?.("tr.o_data_row");
        if (!row || !row.dataset.groupId || ev.ctrlKey || ev.metaKey) {
            return;
        }
        if (ev.altKey && (ev.key === "ArrowUp" || ev.key === "ArrowDown")) {
            ev.preventDefault();
            ev.stopPropagation();
            this.rankByKeyboard(row, ev.key === "ArrowUp" ? -1 : 1);
        } else if (!ev.altKey && !ev.shiftKey && ev.key === "e" && this.canEdit && EDITABLE_COLUMNS.includes(ev.target.closest("td")?.getAttribute("name"))) {
            ev.preventDefault();
            ev.stopPropagation();
            const record = this.recordFor(row);
            if (record && !this.isLockedRecord(record)) {
                this.openEditor(record, ev.target.closest("td").getAttribute("name"), ev.target.closest("td"));
            }
        } else if (!ev.altKey && !ev.shiftKey && ev.key === "m" && ev.target.matches("td, td *:not(input, textarea)")) {
            ev.preventDefault();
            ev.stopPropagation();
            this.openMoveDialog(row);
        }
    }

    async rankByKeyboard(row, direction) {
        const { id: recordId, groupId } = row.dataset;
        const group = this.groupById(groupId);
        const snapshot = this.snapshotRecord(recordId, groupId);
        if (!group || !snapshot) {
            return;
        }
        if (this.isCompletedGroup(group)) {
            this.say(_t("Issues in completed sprints cannot be reordered."), { type: "warning" });
            return;
        }
        const records = group.list.records;
        const target = snapshot.index + direction;
        if (target < 0 || target >= records.length) {
            this.say(boundaryMessage(snapshot.key, direction < 0 ? "first" : "last", this.groupName(group)));
            return;
        }
        const refId = direction < 0 ? records[snapshot.index - 2]?.id ?? null : records[snapshot.index + 1].id;
        try {
            await this.props.list.moveRecord(recordId, groupId, refId, groupId);
        } catch (error) {
            await this.refuseMove(snapshot, error);
            return;
        }
        await this.finishMove(snapshot, groupId);
        this.focusRecordRow(recordId);
    }

    /** Places an issue can go: active sprint, planned sprints, Backlog, top of Backlog. */
    moveTargets(currentGroup) {
        const sprints = (this.info.data?.sprints || []).filter((sprint) => sprint.state !== "done");
        const order = { in_progress: 0, draft: 1 };
        sprints.sort((a, b) => order[a.state] - order[b.state] || a.date_start.localeCompare(b.date_start));
        const targets = sprints
            .filter((sprint) => sprint.id !== currentGroup.value)
            .map((sprint) => ({
                id: `sprint:${sprint.id}`,
                sprintId: sprint.id,
                label: sprint.state === "in_progress" ? _t("%(name)s (active)", { name: sprint.name }) : sprint.name,
            }));
        if (currentGroup.value) {
            targets.push({ id: "backlog", sprintId: false, label: _t("Backlog") });
        }
        targets.push({ id: "backlog-top", sprintId: false, top: true, label: _t("Top of Backlog") });
        return targets;
    }

    openMoveDialog(row) {
        const { id: recordId, groupId } = row.dataset;
        const group = this.groupById(groupId);
        const snapshot = this.snapshotRecord(recordId, groupId);
        if (!group || !snapshot) {
            return;
        }
        if (this.isCompletedGroup(group)) {
            this.say(_t("Issues in completed sprints cannot be moved here."), { type: "warning" });
            return;
        }
        this.dialog.add(AgileMoveToDialog, {
            title: _t("Move %(key)s to", { key: snapshot.key }),
            targets: this.moveTargets(group),
            onSelect: (target) => this.moveTo(snapshot, target),
        });
    }

    async moveTo(snapshot, target) {
        const list = this.props.list;
        const targetGroup = list.groups.find(
            (group) => this.isSprintGroup(group) && (group.value || false) === target.sprintId
        );
        if (!targetGroup) {
            // The target has no section yet (for example an empty Backlog): write the sprint directly.
            try {
                await this.orm.write("project.task", [snapshot.resId], { sprint_id: target.sprintId });
            } catch (error) {
                await this.refuseMove(snapshot, error);
                return;
            }
            await list.model.load();
            this.say(moveMessage(snapshot.key, snapshot.from, { name: target.label, sprint: this.info.data?.sprints.find((s) => s.id === target.sprintId) || null }));
            await this.refreshInfo();
            return;
        }
        const records = targetGroup.list.records;
        const refId = target.top ? null : records.at(-1)?.id ?? null;
        try {
            await list.moveRecord(snapshot.recordId, snapshot.groupId, refId, targetGroup.id);
        } catch (error) {
            await this.refuseMove(snapshot, error);
            return;
        }
        await this.finishMove(snapshot, targetGroup.id);
        this.focusRecordRow(snapshot.recordId);
    }

    // ---- Epic panel: progress per epic, click to filter the backlog ----

    readEpicsOpen() {
        try {
            const saved = browser.localStorage.getItem(EPICS_OPEN_KEY);
            // Nothing saved yet: open on a computer, folded on a phone so the issues start higher up.
            return saved ? saved !== "closed" : !this.uiService.isSmall;
        } catch {
            return !this.uiService.isSmall;
        }
    }

    toggleEpics() {
        this.epics.open = !this.epics.open;
        try {
            browser.localStorage.setItem(EPICS_OPEN_KEY, this.epics.open ? "open" : "closed");
        } catch {
            // Remembering the choice is a convenience only.
        }
    }

    epicProgress(epic) {
        return epicProgress(epic, this.epics.data?.estimate_unit);
    }

    get epicList() {
        return this.epics.data?.epics || [];
    }

    get epicFilter() {
        return this.env.searchModel
            ?.getSearchItems((item) => item.type === "filter" && item.agileEpicId)
            .find((item) => item.isActive);
    }

    get activeEpicId() {
        return this.epicFilter?.agileEpicId || null;
    }

    /** One epic at a time: choosing it filters the backlog, choosing it again clears the filter. */
    selectEpic(epic) {
        const searchModel = this.env.searchModel;
        const active = this.epicFilter;
        if (active) {
            searchModel.toggleSearchItem(active.id);
        }
        if (active?.agileEpicId === epic.id) {
            return;
        }
        const existing = searchModel
            .getSearchItems((item) => item.type === "filter" && item.agileEpicId === epic.id)
            .at(0);
        if (existing) {
            searchModel.toggleSearchItem(existing.id);
            return;
        }
        searchModel.createNewFilters([
            {
                description: _t("Epic: %(name)s", { name: epic.name }),
                domain: `["|", ("parent_id", "=", ${epic.id}), ("parent_id.parent_id", "=", ${epic.id})]`,
                agileEpicId: epic.id,
            },
        ]);
    }


    // ---- Sprint and assignee pick lists above the epics (multi-select) ----

    /** What each pick list offers. The Backlog entry stands for issues that are in no sprint. */
    get isScrum() {
        return !this.props.list.context?.agile_no_sprints;
    }

    /** A new sprint group lands below Backlog in the list; reload so it takes its place above it (OI-3). */
    async addNewGroup() {
        this.state.showGroupInput = false;
        const value = this.groupInputRef.el.value;
        if (value) {
            await this.props.list.createGroup(value);
            await this.props.list.model.load();
        }
    }

    get canCreateGroup() {
        return this.isScrum && super.canCreateGroup;
    }

    get pickLists() {
        const lists = [];
        if (this.isScrum) {
            lists.push(["sprint", "sprint_id", "Sprint", this.sprintChoices]);
        }
        lists.push(["assignee", "user_ids", "Assignee", this.assigneeChoices]);
        return lists;
    }

    get sprintChoices() {
        const sprints = (this.info.data?.sprints || []).map((sprint) => ({
            id: sprint.id,
            label: sprint.name,
            count: sprint.issue_count,
        }));
        return sprints.concat([{ id: false, label: _t("Backlog"), count: this.info.data?.backlog?.issue_count }]);
    }

    get assigneeChoices() {
        return (this.info.data?.members || []).map((member) => ({
            id: member.id,
            label: member.name,
            count: member.issue_count,
        }));
    }

    multiFilter(kind) {
        return this.env.searchModel
            ?.getSearchItems((item) => item.type === "filter" && item.agileMulti === kind)
            .find((item) => item.isActive);
    }

    multiIds(kind) {
        return this.multiFilter(kind)?.agileIds || [];
    }

    multiSummary(kind, title, choices) {
        const ids = this.multiIds(kind);
        if (!ids.length) {
            return title;
        }
        const names = choices.filter((choice) => ids.includes(choice.id)).map((choice) => choice.label);
        return names.length === 1 ? `${title}: ${names[0]}` : _t("%(title)s: %(count)s selected", { title, count: names.length });
    }

    /** Tick or untick one choice; the picks become one search filter shown in the search box. */
    toggleMulti(kind, field, title, choices, id) {
        const searchModel = this.env.searchModel;
        const current = this.multiIds(kind);
        const ids = current.includes(id) ? current.filter((value) => value !== id) : [...current, id];
        const active = this.multiFilter(kind);
        if (active) {
            searchModel.toggleSearchItem(active.id);
        }
        if (!ids.length) {
            return;
        }
        const key = `${kind}:${ids.map(String).sort().join(",")}`;
        const existing = searchModel
            .getSearchItems((item) => item.type === "filter" && item.agileKey === key)
            .at(0);
        if (existing) {
            searchModel.toggleSearchItem(existing.id);
            return;
        }
        const names = choices.filter((choice) => ids.includes(choice.id)).map((choice) => choice.label);
        searchModel.createNewFilters([
            {
                description: `${title}: ${names.join(", ")}`,
                domain: JSON.stringify([[field, "in", ids]]),
                agileMulti: kind,
                agileIds: ids,
                agileKey: key,
            },
        ]);
    }

    clearMulti(kind) {
        const active = this.multiFilter(kind);
        if (active) {
            this.env.searchModel.toggleSearchItem(active.id);
        }
    }

    // ---- Inline edit and quick create (spec section 12) ----

    get canEdit() {
        return Boolean(this.info.data?.can_edit);
    }

    /** Styling hook: cells only look editable once the header data says the user may edit. */
    syncEditable() {
        this.rootRef.el?.classList.toggle("o_ag_can_edit", this.canEdit);
    }

    recordFor(row) {
        const group = this.groupById(row.dataset.groupId);
        return group?.list.records.find((record) => record.id === row.dataset.id) || null;
    }

    isLockedRecord(record) {
        const sprintId = record.data.sprint_id?.id ?? record.data.sprint_id?.[0];
        return this.info.data?.sprints.find((item) => item.id === sprintId)?.state === "done";
    }

    /** On a phone the handle cell is a menu button: move, assign, rank (no hidden gestures). */
    openRowSheet(row) {
        const { id: recordId, groupId } = row.dataset;
        const group = this.groupById(groupId);
        const snapshot = this.snapshotRecord(recordId, groupId);
        const record = this.recordFor(row);
        if (!group || !snapshot || !record) {
            return;
        }
        if (this.isCompletedGroup(group)) {
            this.say(_t("Issues in completed sprints cannot be changed here."), { type: "warning" });
            return;
        }
        const actions = [{ id: "move", label: _t("Move to sprint…") }];
        if (this.canEdit && !this.isLockedRecord(record)) {
            actions.push({ id: "assign", label: _t("Assign…") });
        }
        actions.push({ id: "up", label: _t("Rank up") }, { id: "down", label: _t("Rank down") });
        this.dialog.add(AgileRowSheet, {
            title: snapshot.key,
            actions,
            onSelect: ({ id }) => {
                if (id === "move") {
                    this.openMoveDialog(row);
                } else if (id === "assign") {
                    const cell = row.querySelector('td[name="user_ids"]');
                    this.openEditor(record, "user_ids", cell || row);
                } else {
                    this.rankByKeyboard(row, id === "up" ? -1 : 1);
                }
            },
        });
    }

    onBacklogClick(ev) {
        const handle = this.uiService.isSmall && ev.target.closest?.("tr.o_data_row td.o_handle_cell");
        if (handle && !ev.button) {
            ev.preventDefault();
            ev.stopPropagation();
            this.openRowSheet(handle.closest("tr"));
            return;
        }
        if (!this.canEdit || ev.button || ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.altKey) {
            return;
        }
        const cell = ev.target.closest?.("tr.o_data_row td.o_data_cell");
        const row = cell?.closest("tr");
        if (!cell || !EDITABLE_COLUMNS.includes(cell.getAttribute("name"))) {
            return;
        }
        const record = this.recordFor(row);
        if (!record || this.isLockedRecord(record) || this.props.list.selection.length) {
            return;
        }
        ev.preventDefault();
        ev.stopPropagation();
        this.openEditor(record, cell.getAttribute("name"), cell);
    }

    openEditor(record, fieldName, cell) {
        const info = this.info.data;
        const key = record.data.issue_key || record.data.name;
        this.editTarget = cell;
        let spec;
        if (fieldName === "story_points") {
            spec = {
                kind: "number",
                label: _t("Points for %(key)s", { key }),
                value: record.data.story_points_estimated ? String(record.data.story_points) : "",
                save: (points) =>
                    this.saveField(record, key, points === null
                        ? { story_points_estimated: false, story_points: 0 }
                        : { story_points_estimated: true, story_points: points }, _t("%(key)s estimate saved.", { key })),
            };
        } else if (fieldName === "user_ids") {
            const current = record.data.user_ids?.currentIds?.[0] ?? "";
            spec = {
                kind: "select",
                label: _t("Assignee for %(key)s", { key }),
                value: current,
                options: [{ id: "", label: _t("Unassigned") }].concat(
                    info.members.map((member) => ({ id: member.id, label: member.name }))
                ),
                save: (userId) =>
                    this.saveField(record, key, { user_ids: [[6, 0, userId ? [userId] : []]] }, _t("%(key)s assignee saved.", { key })),
            };
        } else {
            spec = {
                kind: "select",
                label: _t("Type for %(key)s", { key }),
                value: record.data.agile_task_type_id?.id ?? record.data.agile_task_type_id?.[0] ?? "",
                options: info.task_types.map((type) => ({ id: type.id, label: type.name })),
                save: (typeId) =>
                    this.saveField(record, key, { agile_task_type_id: typeId }, _t("%(key)s type saved.", { key })),
            };
        }
        this.editor.open(cell, {
            label: spec.label,
            kind: spec.kind,
            value: spec.value,
            options: spec.options,
            onSave: spec.save,
        });
    }

    /** Write straight to the server so a refusal never leaves a half-edited row behind. */
    async saveField(record, key, values, doneMessage) {
        await this.orm.write("project.task", [record.resId], values);
        await record.load();
        this.announce(doneMessage);
        await this.refreshInfo();
    }

    quickAllowed(group) {
        if (!this.canEdit || !this.isSprintGroup(group) || !this.info.data?.task_types.length) {
            return false;
        }
        if (!group.value) {
            return true;
        }
        const sprint = this.sprintFor(group);
        return Boolean(sprint && sprint.state !== "done" && sprint.can_manage);
    }

    quickTypeId() {
        return this.quick.typeId ?? this.info.data?.task_types[0]?.id;
    }

    setQuickType(typeId) {
        this.quick.typeId = typeId;
    }

    async createIssue(group, { title, typeId, userId }) {
        const values = {
            name: title,
            project_id: this.projectId,
            agile_task_type_id: typeId,
        };
        // Unassigned must say so: left out, Odoo assigns the creator, and a rule then adds a second person (NU-11).
        values.user_ids = [[6, 0, userId ? [userId] : []]];
        if (group.value) {
            values.sprint_id = group.value;
        }
        const [id] = await this.orm.create("project.task", [values]);
        const [issue] = await this.orm.read("project.task", [id], ["issue_key"]);
        this.refocusQuick = String(group.value || 0);
        await this.props.list.model.load();
        this.say(
            _t("%(key)s created in %(group)s.", { key: issue.issue_key, group: this.groupName(group) })
        );
        await this.refreshInfo();
    }

    quickGroupKey(group) {
        return String(group.value || 0);
    }


    async runSprintAction(sprint, method) {
        const refresh = async () => {
            this.infoKey = null;
            await this.props.list.model.load();
        };
        await this.action.doActionButton({
            type: "object",
            name: method,
            resModel: "project.sprint",
            resId: sprint.id,
            context: {},
            // Starting a sprint opens a dialog: reload when it closes, not only when it opens.
            onClose: refresh,
        });
        await refresh();
    }

    // ---- bulk edit (S-931): the native row checkboxes select, the bar below changes them ----

    get selectedIds() {
        return (this.props.list.selection || []).map((record) => record.resId).filter(Boolean);
    }

    get bulkProjectId() {
        // A person who cannot edit gets no bulk bar: every change would be refused (E2E-003).
        return this.canEdit ? this.info.data?.project_id : false;
    }

    allRecords() {
        return this.props.list.records;
    }

    /** After a bulk change: reload, unselect what changed and keep the refused ones selected. */
    async onBulkDone({ refused }) {
        await this.props.list.model.load();
        await this.refreshInfo();
        for (const record of this.allRecords()) {
            record.toggleSelection(refused.includes(record.resId));
        }
    }

    clearSelection() {
        for (const record of this.allRecords()) {
            record.toggleSelection(false);
        }
    }

    groupSelected(group) {
        const records = group.list?.records || [];
        return records.length > 0 && records.every((record) => record.selected);
    }

    toggleGroupSelection(group, ev) {
        for (const record of group.list.records) {
            record.toggleSelection(ev.target.checked);
        }
    }

    /** Open the Reports page on one report for a sprint or epic; Back returns to the Backlog. */
    async openReport(report, recordId) {
        const action = await this.orm.call("agile.report", "report_action", [
            this.info.data.project_id,
            report,
            recordId,
        ]);
        await this.action.doAction(action);
    }

    completeSprint(sprint) {
        return this.action.doAction("agile_scrum.action_project_sprint_close", {
            additionalContext: { active_id: sprint.id },
            onClose: async () => {
                this.infoKey = null;
                await this.props.list.model.load();
                await this.refreshInfo();
            },
        });
    }

    async reopenSprint(sprint) {
        const action = await this.orm.call("project.sprint", "action_agile_open_reopen", [[sprint.id]]);
        return this.action.doAction(action, {
            onClose: async () => {
                this.infoKey = null;
                await this.props.list.model.load();
                await this.refreshInfo();
            },
        });
    }

    openSprint(sprint) {
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "project.sprint",
            res_id: sprint.id,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

export class AgileBacklogController extends ListController {
    get hideCompletedItem() {
        return this.env.searchModel
            .getSearchItems((item) => item.type === "filter" && item.name === HIDE_COMPLETED_FILTER)
            .at(0);
    }

    /** Kanban projects have no sprints, so the sprint buttons stay away (NU-48). */
    get isScrum() {
        return !this.props.context?.agile_no_sprints;
    }

    get completedHidden() {
        return Boolean(this.hideCompletedItem?.isActive);
    }

    toggleCompleted() {
        const item = this.hideCompletedItem;
        if (item) {
            this.env.searchModel.toggleSearchItem(item.id);
        }
    }
}

export const agileBacklogListView = {
    ...listView,
    Controller: AgileBacklogController,
    Renderer: AgileBacklogRenderer,
    buttonTemplate: "agile_community.BacklogButtons",
};

registry.category("views").add("agile_backlog_list", agileBacklogListView);
