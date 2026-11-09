import { signal } from "@odoo/owl";
import { Component, proxy, useProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";

import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { buildModel, hasMove, recordKey, reorder, sequencesFor } from "./workflow_canvas_helpers";

export const BOX = { w: 132, h: 58, gap: 64, pad: 16 };
const ARC = { base: 26, perStep: 30 };
const ZONES = [
    { key: "backlog", label: _t("Backlog: outside the sprint"), categories: ["backlog"] },
    { key: "sprint", label: _t("In a sprint: the board columns"), categories: ["ready", "progress", "review", "done"] },
    { key: "closed", label: _t("Closed"), categories: ["canceled"] },
];
// What each category means, in the words the Add status panel shows.
export const CATEGORY_CHOICES = [
    { value: "backlog", label: _t("Backlog"), hint: _t("not planned into a sprint yet") },
    { value: "ready", label: _t("To Do"), hint: _t("planned, waiting to start") },
    { value: "progress", label: _t("In Progress"), hint: _t("someone is working on it") },
    { value: "review", label: _t("Review"), hint: _t("waiting for someone to check it") },
    { value: "done", label: _t("Done"), hint: _t("finished and counted as delivered") },
    { value: "canceled", label: _t("Canceled"), hint: _t("will not be done") },
];
const SPREAD = 9; // pixels between arrows that meet the same side of a box

/** Who may take a move, in words (the picture never relies on colour or line style alone). */
export function rolesText(roles) {
    if (!roles.length) {
        return _t("nobody");
    }
    return roles.join(", ").toLowerCase();
}

/** The arrow's text: the button name, and in brackets who only may take it and how many conditions it has. */
export function arrowLabel(move, managersOnly) {
    const notes = [];
    if (managersOnly) {
        notes.push(_t("managers"));
    }
    const count = move.conditions?.length || 0;
    if (count) {
        notes.push(count === 1 ? _t("1 rule") : _t("%(count)s rules", { count }));
    }
    const actions = move.actions?.length || 0;
    if (actions) {
        notes.push(actions === 1 ? _t("1 action") : _t("%(count)s actions", { count: actions }));
    }
    return notes.length ? `${move.name} (${notes.join(", ")})` : move.name;
}

function conditionsAria(move) {
    const parts = [];
    const rules = move.conditions?.length || 0;
    if (rules) {
        parts.push(
            (rules === 1 ? _t("1 rule") : _t("%(count)s rules", { count: rules })) +
                _t(": needs %(list)s", { list: move.conditions.join(" and ") })
        );
    }
    const actions = move.actions?.length || 0;
    if (actions) {
        parts.push(actions === 1 ? _t("1 action runs afterwards") : _t("%(count)s actions run afterwards", { count: actions }));
    }
    return parts.length ? ", " + parts.join(", ") : "";
}

/**
 * Lay the statuses out left to right and the moves as arcs: forward moves above the row,
 * backward moves below. Moves only managers may take are dashed and say "(managers)".
 */
export function flowLayout(diagram) {
    const statuses = diagram?.statuses || [];
    const index = new Map(statuses.map((status, i) => [status.stage_id, i]));
    const boxes = statuses.map((status, i) => ({
        ...status,
        x: BOX.pad + i * (BOX.w + BOX.gap),
        y: 0,
        w: BOX.w,
        h: BOX.h,
    }));
    const moves = (diagram?.moves || []).filter((move) => index.has(move.from) && index.has(move.to));
    let up = 0;
    let down = 0;
    // Arrows that leave or arrive on the same side of one box fan out instead of landing on one point.
    const seen = new Map();
    const slot = (key) => {
        const n = seen.get(key) || 0;
        seen.set(key, n + 1);
        return n;
    };
    const arrows = moves.map((move) => {
        const a = index.get(move.from);
        const b = index.get(move.to);
        const forward = a < b;
        const rise = ARC.base + ARC.perStep * Math.abs(b - a);
        // Arrows leave and arrive at slightly different spots so parallel moves stay readable.
        const x1 = boxes[a].x + BOX.w / 2 + (forward ? 12 : -12) + slot(`out${a}${forward}`) * SPREAD * (forward ? 1 : -1);
        const x2 = boxes[b].x + BOX.w / 2 + (forward ? -12 : 12) + slot(`in${b}${forward}`) * SPREAD * (forward ? -1 : 1);
        const managersOnly = move.roles.length === 1 && move.roles[0] === "Managers";
        if (forward) {
            up = Math.max(up, rise);
        } else {
            down = Math.max(down, rise);
        }
        return {
            ...move,
            forward,
            rise,
            x1,
            x2,
            dashed: managersOnly,
            label: arrowLabel(move, managersOnly),
            aria: _t("Move %(name)s: %(from)s to %(to)s, %(roles)s", {
                name: move.name,
                from: boxes[a].name,
                to: boxes[b].name,
                roles: rolesText(move.roles),
            }) + conditionsAria(move),
        };
    });
    // Several moves with one name into the same status (every Cancel into Canceled) get one label,
    // on the longest arc, so the words do not pile up. The other arcs still carry it for screen readers.
    const groups = new Map();
    for (const arrow of arrows) {
        const key = `${arrow.to}|${arrow.forward}|${arrow.name}`;
        groups.set(key, [...(groups.get(key) || []), arrow]);
    }
    for (const group of groups.values()) {
        const lead = group.reduce((best, arrow) => (arrow.rise > best.rise ? arrow : best), group[0]);
        for (const arrow of group) {
            arrow.showLabel = arrow === lead;
            arrow.shownLabel = group.length > 1 && arrow === lead
                ? _t("%(label)s, from %(count)s statuses", { label: arrow.label, count: group.length })
                : arrow.label;
        }
    }
    const top = up + 28;
    for (const box of boxes) {
        box.y = top;
        // The dot under a box: drag from it onto another box to add a move.
        box.portX = box.x + BOX.w / 2;
        box.portY = top + BOX.h + 8;
    }
    for (const arrow of arrows) {
        const y = top + (arrow.forward ? 0 : BOX.h);
        const dir = arrow.forward ? -1 : 1;
        const cx = (arrow.x1 + arrow.x2) / 2;
        arrow.d = `M ${arrow.x1} ${y} Q ${cx} ${y + dir * arrow.rise * 1.6} ${arrow.x2} ${y}`;
        arrow.lx = cx;
        arrow.ly = y + dir * (arrow.rise * 0.8 + 4);
    }
    // Brackets under the row say where each status lives: the backlog is outside the sprint,
    // To Do to Done are the sprint board, Canceled is closed work.
    const bracketY = top + BOX.h + down + 20;
    const brackets = ZONES.map((zone) => {
        const inZone = boxes.filter((box) => zone.categories.includes(box.category));
        if (!inZone.length) {
            return null;
        }
        const x1 = inZone[0].x;
        const x2 = inZone.at(-1).x + BOX.w;
        return { key: zone.key, label: zone.label, x1, x2, y: bracketY, cx: (x1 + x2) / 2 };
    }).filter(Boolean);
    return {
        boxes,
        arrows,
        brackets,
        width: BOX.pad * 2 + Math.max(statuses.length, 1) * (BOX.w + BOX.gap) - BOX.gap,
        height: top + BOX.h + down + 36 + (brackets.length ? 28 : 0),
    };
}

const NEED_NAMES_FALLBACK = [];

/**
 * The flow picture on the workflow form. It reads the Statuses and Moves lists, so it redraws as they
 * change, and it edits them: drag a box to reorder, drag from its dot onto another box to add a move,
 * click a box or an arrow for the side panel (D-806). Without edit rights it stays a read-only picture.
 */
export class AgileWorkflowDiagram extends Component {
    static template = "agile_community.WorkflowDiagram";
    props = useProps({ ...standardFieldProps });

    setup() {
        this.rootRef = signal.ref();
        this.svgRef = signal.ref();
        this.orm = useService("orm");
        this.categories = CATEGORY_CHOICES;
        this.state = proxy({ sel: null, drag: null, message: "", undo: [], adding: null, ask: null, moveTo: "", actionType: "priority" });
    }

    get statusList() {
        return this.props.record.data.status_ids;
    }

    get moveList() {
        return this.props.record.data.transition_ids;
    }

    get editable() {
        // The picture field itself is computed, so it is always read-only; the lists decide.
        const diagram = this.props.record.data[this.props.name];
        return Boolean(diagram?.editable && this.statusList?.records && this.moveList?.records);
    }

    get model() {
        if (this.editable) {
            return buildModel(this.statusList.records, this.moveList.records);
        }
        return this.props.record.data[this.props.name] || { statuses: [], moves: [] };
    }

    get layout() {
        return flowLayout(this.model);
    }

    get people() {
        return this.props.record.data[this.props.name]?.people || NEED_NAMES_FALLBACK;
    }

    get needs() {
        return this.props.record.data[this.props.name]?.needs || NEED_NAMES_FALLBACK;
    }

    // ---- reading ----

    countText(box) {
        let text = _t("no issues");
        if (box.count) {
            text = box.count === 1 ? _t("1 issue") : _t("%(count)s issues", { count: box.count });
        }
        return box.hidden ? _t("hidden, %(text)s", { text }) : text;
    }

    boxLabel(box) {
        const base = _t("Status %(name)s, %(count)s", { name: box.name, count: this.countText(box) });
        return this.editable ? `${base}. ${_t("Alt plus Left or Right arrow moves it.")}` : base;
    }

    boxX(box) {
        const drag = this.state.drag;
        return drag?.mode === "move" && drag.key === box.stage_id ? drag.x : box.x;
    }

    get selectedBox() {
        const sel = this.state.sel;
        return sel?.type === "status" ? this.model.statuses.find((s) => s.stage_id === sel.key) : null;
    }

    get selectedMove() {
        const sel = this.state.sel;
        return sel?.type === "move" ? this.model.moves.find((m) => m.id === sel.key) : null;
    }

    /** Statuses a move from the selected status could go to (no move exists yet). */
    get targets() {
        const box = this.selectedBox;
        if (!box) {
            return [];
        }
        return this.model.statuses.filter(
            (s) => s.stage_id !== box.stage_id && !hasMove(this.model.moves, box.stage_id, s.stage_id)
        );
    }

    get customNeeds() {
        return this.props.record.data[this.props.name]?.custom_needs || NEED_NAMES_FALLBACK;
    }

    statusName(key) {
        return this.model.statuses.find((s) => s.stage_id === key)?.name || "";
    }

    hasNeed(move, needId) {
        return move.record.data.required_field_ids.currentIds.includes(needId);
    }

    hasCustomNeed(move, needId) {
        return move.record.data.required_custom_field_ids.currentIds.includes(needId);
    }

    /** Take the person to the list row the picture shows, and flash it (read-only picture). */
    show(fieldName, text) {
        const form = this.rootRef().closest(".o_form_view");
        const rows = [...(form?.querySelectorAll(`.o_field_widget[name="${fieldName}"] tr.o_data_row`) || [])];
        const row = rows.find((el) => el.innerText.includes(text));
        if (!row) {
            return;
        }
        row.scrollIntoView?.({ block: "center" });
        row.classList.add("o_ag_flash");
        row.querySelector("td")?.focus?.();
        setTimeout(() => row.classList.remove("o_ag_flash"), 1200);
    }

    onKey(ev, callback) {
        if (ev.key === "Enter" || ev.key === " ") {
            ev.preventDefault();
            callback();
        }
    }

    // ---- picking ----

    clickBox(box) {
        if (!this.editable) {
            return this.show("status_ids", box.name);
        }
        this.state.message = "";
        this.state.sel = { type: "status", key: box.stage_id };
    }

    clickArrow(arrow) {
        if (!this.editable) {
            return this.show("transition_ids", arrow.name);
        }
        this.state.message = "";
        this.state.sel = { type: "move", key: arrow.id };
    }

    // ---- pointer: drag a box, or drag from its dot ----

    point(ev) {
        const svg = this.svgRef();
        const rect = svg.getBoundingClientRect();
        const box = svg.viewBox.baseVal;
        return [((ev.clientX - rect.left) * box.width) / rect.width, ((ev.clientY - rect.top) * box.height) / rect.height];
    }

    boxAt(x, y) {
        return this.layout.boxes.find((b) => x >= b.x && x <= b.x + b.w && y >= b.y && y <= b.y + b.h);
    }

    onPointerDown(ev) {
        if (!this.editable) {
            return;
        }
        const port = ev.target.closest("[data-port]");
        const boxEl = ev.target.closest("[data-key]");
        const arrowEl = ev.target.closest("[data-arrow]");
        if (arrowEl) {
            this.clickArrow({ id: Number(arrowEl.dataset.arrow) || arrowEl.dataset.arrow });
            return;
        }
        const key = Number(port?.dataset.port || boxEl?.dataset.key);
        const box = this.layout.boxes.find((b) => b.stage_id === key);
        if (!box) {
            return;
        }
        const [px] = this.point(ev);
        this.svgRef().setPointerCapture?.(ev.pointerId);
        this.state.drag = port
            ? { mode: "link", key, over: null, line: null }
            : { mode: "move", key, x: box.x, offset: px - box.x, moved: false, startX: box.x };
    }

    onPointerMove(ev) {
        const drag = this.state.drag;
        if (!drag) {
            return;
        }
        const [px, py] = this.point(ev);
        if (drag.mode === "move") {
            const last = this.layout.boxes.at(-1);
            drag.x = Math.max(BOX.pad, Math.min(px - drag.offset, last.x));
            drag.moved = drag.moved || Math.abs(drag.x - drag.startX) > 6;
        } else {
            const from = this.layout.boxes.find((b) => b.stage_id === drag.key);
            const over = this.boxAt(px, py);
            drag.over = over && over.stage_id !== drag.key ? over.stage_id : null;
            drag.line = [from.portX, from.portY, px, py];
        }
    }

    async onPointerUp(ev) {
        const drag = this.state.drag;
        if (!drag) {
            return;
        }
        this.state.drag = null;
        const [px, py] = this.point(ev);
        if (drag.mode === "move") {
            if (!drag.moved) {
                return this.clickBox(this.layout.boxes.find((b) => b.stage_id === drag.key));
            }
            const slot = BOX.w + BOX.gap;
            await this.moveStatus(drag.key, Math.round((drag.x - BOX.pad) / slot));
            this.state.sel = { type: "status", key: drag.key };
        } else {
            const over = this.boxAt(px, py);
            if (over && over.stage_id !== drag.key) {
                await this.addMove(drag.key, over.stage_id);
            }
        }
    }

    onSvgKey(ev) {
        const boxEl = ev.target.closest("[data-key]");
        const arrowEl = ev.target.closest("[data-arrow]");
        if (this.editable && boxEl && ev.altKey && (ev.key === "ArrowLeft" || ev.key === "ArrowRight")) {
            ev.preventDefault();
            const key = Number(boxEl.dataset.key);
            const index = this.model.statuses.findIndex((s) => s.stage_id === key);
            this.moveStatus(key, index + (ev.key === "ArrowLeft" ? -1 : 1));
            return;
        }
        if (ev.key === "Enter" || ev.key === " ") {
            ev.preventDefault();
            if (boxEl) {
                this.clickBox(this.layout.boxes.find((b) => b.stage_id === Number(boxEl.dataset.key)));
            } else if (arrowEl) {
                this.clickArrow({ id: Number(arrowEl.dataset.arrow) || arrowEl.dataset.arrow, name: "" });
            }
        }
    }

    // ---- adding and renaming statuses (B-911) ----

    openAdd() {
        this.state.sel = null;
        this.state.ask = null;
        this.state.adding = { name: "", category: "progress", error: "", busy: false };
    }

    cancelAdd() {
        this.state.adding = null;
    }

    /** A free name check for instant feedback; the server checks again when saving. */
    nameTaken(name, exceptKey = null) {
        const wanted = name.trim().toLowerCase();
        return this.model.statuses.some((box) => box.stage_id !== exceptKey && box.name.trim().toLowerCase() === wanted);
    }

    async addStatus() {
        const form = this.state.adding;
        const name = form.name.trim();
        if (!name) {
            form.error = _t("Give the status a name.");
            return;
        }
        if (this.nameTaken(name)) {
            form.error = _t("A status called %(name)s already exists.", { name });
            return;
        }
        form.busy = true;
        form.error = "";
        const record = this.props.record;
        try {
            // The new status is saved at once, so unsaved edits are saved first and nothing is lost.
            if (record.dirty && !(await record.save())) {
                form.error = _t("Fix the highlighted fields, then add the status.");
                return;
            }
            const result = await this.orm.call("agile.workflow", "agile_add_status", [[record.resId], name, form.category]);
            await record.load();
            this.state.undo = [];
            this.state.adding = null;
            this.state.sel = { type: "status", key: result.status_id };
            this.state.message = _t(
                "%(name)s added. It has no moves yet, so issues cannot reach it. Draw a move to it.",
                { name }
            );
        } catch (error) {
            form.error = error?.data?.message || error?.message || _t("The status could not be added.");
        } finally {
            form.busy = false;
        }
    }

    stageOf(box) {
        const value = box.record.data.stage_id;
        return value?.id ?? value?.[0];
    }

    /** Project statuses this workflow does not use yet. */
    get available() {
        return this.props.record.data[this.props.name]?.available || [];
    }

    /** Where the issues of a status being hidden can go: other shown statuses, same category first. */
    moveTargets(box) {
        return this.model.statuses
            .filter((s) => s.stage_id !== box.stage_id && !s.hidden)
            .sort((a, b) => (b.category === box.category) - (a.category === box.category));
    }

    /**
     * Run a status change on the server. These save at once (the form's unsaved edits are saved first),
     * then the form reloads so the picture and lists show what the server holds.
     */
    async serverStatus(method, args, done) {
        const record = this.props.record;
        try {
            if (record.dirty && !(await record.save())) {
                this.state.message = _t("Fix the highlighted fields, then try again.");
                return false;
            }
            const result = await this.orm.call("agile.workflow", method, [[record.resId], ...args]);
            await record.load();
            this.state.undo = [];
            this.state.ask = null;
            this.state.adding = null;
            this.state.sel = done.select ? { type: "status", key: done.select(result) } : null;
            this.state.message = done.message;
            return true;
        } catch (error) {
            this.state.message = error?.data?.message || error?.message || _t("The change could not be saved.");
            return false;
        }
    }

    hideStatus(box) {
        const target = box.count ? Number(this.state.moveTo) || null : null;
        if (box.count && !target) {
            this.state.message = _t("%(count)s issues are in %(name)s. Choose a status to move them to.", {
                count: box.count,
                name: box.name,
            });
            return;
        }
        return this.serverStatus("agile_hide_status", [this.stageOf(box), target], {
            message: _t("%(name)s is hidden. Show it again from its box.", { name: box.name }),
        });
    }

    showStatus(box) {
        return this.serverStatus("agile_show_status", [this.stageOf(box)], {
            select: () => box.stage_id,
            message: _t("%(name)s is shown again.", { name: box.name }),
        });
    }

    askFirst(kind) {
        this.state.ask = kind;
    }

    removeStatus(box) {
        return this.serverStatus("agile_remove_status", [this.stageOf(box)], {
            message: _t("%(name)s is out of this workflow. The project still has it.", { name: box.name }),
        });
    }

    deleteStatus(box) {
        return this.serverStatus("agile_delete_status", [this.stageOf(box)], {
            message: _t("%(name)s is deleted.", { name: box.name }),
        });
    }

    useStatus(ev) {
        const stageId = Number(ev.target.closest(".o_ag_use_status").querySelector("select").value);
        if (!stageId) {
            return;
        }
        const entry = this.available.find((item) => item.stage_id === stageId);
        return this.serverStatus("agile_use_status", [stageId], {
            select: (result) => result.status_id,
            message: _t("%(name)s added to this workflow. Draw its moves.", { name: entry?.name || "" }),
        });
    }

    async renameStatus(ev, box) {
        const name = ev.target.value.trim();
        if (!name || name === box.name) {
            ev.target.value = box.name;
            return;
        }
        if (this.nameTaken(name, box.stage_id)) {
            this.state.message = _t("A status called %(name)s already exists.", { name });
            ev.target.value = box.name;
            return;
        }
        this.beginEdit();
        const before = box.name;
        await box.record.update({ name });
        this.pushUndo(() => box.record.update({ name: before }));
        this.state.message = _t("%(before)s is now called %(name)s. Save the form to keep it.", { before, name });
    }

    categoryLabel(value) {
        return this.categories.find((choice) => choice.value === value)?.label || value;
    }

    // ---- editing: every change goes through the form's own lists and can be undone ----

    async moveStatus(key, target) {
        this.beginEdit();
        const keys = this.model.statuses.map((s) => s.stage_id);
        const index = keys.indexOf(key);
        if (index < 0 || target < 0 || target >= keys.length || target === index) {
            return;
        }
        const before = Object.fromEntries(this.model.statuses.map((s) => [s.stage_id, s.record.data.sequence]));
        await this.applySequences(sequencesFor(reorder(keys, key, target)));
        this.pushUndo(() => this.applySequences(before));
        this.state.message = _t("%(name)s is now number %(n)s.", { name: this.statusName(key), n: target + 1 });
    }

    async applySequences(sequences) {
        for (const status of this.model.statuses) {
            const sequence = sequences[status.stage_id];
            if (sequence !== undefined && sequence !== status.record.data.sequence) {
                await status.record.update({ sequence });
            }
        }
    }

    async addMove(from, to) {
        this.beginEdit();
        if (hasMove(this.model.moves, from, to)) {
            this.state.message = _t("A move from %(from)s to %(to)s already exists.", {
                from: this.statusName(from),
                to: this.statusName(to),
            });
            return;
        }
        const record = await this.moveList.addNewRecord({ position: "bottom", mode: "readonly" });
        // The button is named after where it leads, and every team member may take it (NU-08).
        await this.fillMove(record, {
            name: _t("Move to %(to)s", { to: this.statusName(to) }),
            from,
            to,
            contributor: true,
            reviewer: true,
        });
        this.pushUndo(() => this.moveList.delete(record));
        this.state.sel = { type: "move", key: recordKey(record) };
        this.state.message = _t("Added a move from %(from)s to %(to)s. All team members can take it. Choose who may in the panel.", {
            from: this.statusName(from),
            to: this.statusName(to),
        });
    }

    fillMove(record, { name, from, to, contributor = false, reviewer = false, manager = true, subtasks = false, notBlocked = false }) {
        return record.update({
            require_no_open_subtasks: subtasks,
            require_not_blocked: notBlocked,
            name,
            from_status_id: { id: from, display_name: this.statusName(from) },
            to_status_id: { id: to, display_name: this.statusName(to) },
            allow_contributor: contributor,
            allow_reviewer: reviewer,
            allow_manager: manager,
        });
    }

    async editMove(move, changes) {
        this.beginEdit();
        const before = Object.fromEntries(Object.keys(changes).map((field) => [field, move.record.data[field]]));
        await move.record.update(changes);
        this.pushUndo(() => move.record.update(before));
    }

    onName(ev, move) {
        const name = ev.target.value.trim();
        if (name && name !== move.name) {
            return this.editMove(move, { name });
        }
        ev.target.value = move.name;
    }

    onRole(ev, move, field) {
        return this.editMove(move, { [field]: ev.target.checked });
    }

    onCondition(ev, move, field) {
        return this.editMove(move, { [field]: ev.target.checked });
    }

    async toggleNeed(move, needId) {
        this.beginEdit();
        const list = move.record.data.required_field_ids;
        const on = list.currentIds.includes(needId);
        const change = on ? { remove: [needId] } : { add: [needId] };
        const reverse = on ? { add: [needId] } : { remove: [needId] };
        await list.addAndRemove(change);
        this.pushUndo(() => list.addAndRemove(reverse));
    }

    async toggleCustomNeed(move, needId) {
        this.beginEdit();
        const list = move.record.data.required_custom_field_ids;
        const on = list.currentIds.includes(needId);
        const change = on ? { remove: [needId] } : { add: [needId] };
        const reverse = on ? { add: [needId] } : { remove: [needId] };
        await list.addAndRemove(change);
        this.pushUndo(() => list.addAndRemove(reverse));
    }

    async addAction(ev, move) {
        const panel = ev.target.closest(".o_ag_actions");
        const type = panel.querySelector(".o_ag_action_type").value;
        const value = panel.querySelector(".o_ag_action_value")?.value?.trim();
        if (!value) {
            this.state.message = _t("Choose or write what the action should do.");
            return;
        }
        const values = {
            name: _t("From the workflow: %(name)s", { name: move.name }),
            project_id: this.props.record.data.project_id,
            trigger: "transition",
        };
        if (type === "priority") {
            Object.assign(values, { action_type: "set_field", set_field_name: "priority", set_priority: value });
        } else if (type === "assign") {
            const person = this.people.find((item) => item.id === Number(value));
            Object.assign(values, {
                action_type: "assign",
                assign_user_id: { id: person.id, display_name: person.name },
            });
        } else if (type === "notify") {
            Object.assign(values, { action_type: "notify", notify_assignees: true, message: value });
        } else {
            Object.assign(values, { action_type: "comment", message: value });
        }
        this.beginEdit();
        const list = move.record.data.action_ids;
        const record = await list.addNewRecord({ position: "bottom", mode: "readonly" });
        await record.update(values);
        this.pushUndo(() => list.delete(record));
        this.state.message = _t("Added an action to %(name)s. Save the form to keep it.", { name: move.name });
    }

    async removeAction(move, action) {
        this.beginEdit();
        const list = move.record.data.action_ids;
        await list.delete(action.record);
        this.state.message = _t("Removed the action from %(name)s. Save the form to keep it.", { name: move.name });
    }

    async deleteMove(move) {
        this.beginEdit();
        const data = move.record.data;
        const snapshot = {
            name: data.name,
            from: move.from,
            to: move.to,
            contributor: data.allow_contributor,
            reviewer: data.allow_reviewer,
            manager: data.allow_manager,
            subtasks: data.require_no_open_subtasks,
            notBlocked: data.require_not_blocked,
            needs: [...data.required_field_ids.currentIds],
            customNeeds: [...data.required_custom_field_ids.currentIds],
        };
        await this.moveList.delete(move.record);
        this.state.sel = null;
        this.state.message = _t("Removed the move %(name)s.", { name: snapshot.name });
        this.pushUndo(async () => {
            const record = await this.moveList.addNewRecord({ position: "bottom", mode: "readonly" });
            await this.fillMove(record, snapshot);
            if (snapshot.needs.length) {
                await record.data.required_field_ids.addAndRemove({ add: snapshot.needs });
            }
            if (snapshot.customNeeds.length) {
                await record.data.required_custom_field_ids.addAndRemove({ add: snapshot.customNeeds });
            }
        });
    }

    onAddMove(ev, box) {
        const to = Number(ev.target.closest(".o_ag_panel").querySelector("select").value);
        if (to) {
            return this.addMove(box.stage_id, to);
        }
    }

    /** Call before the first change: remember if the form was untouched, so undoing all can leave it so. */
    beginEdit() {
        if (!this.state.undo.length) {
            this.cleanBeforeEdits = !this.props.record.dirty;
        }
    }

    pushUndo(step) {
        this.state.undo.push(step);
    }

    async undo() {
        const step = this.state.undo.pop();
        if (step) {
            await step();
            if (!this.state.undo.length && this.cleanBeforeEdits) {
                // Every canvas edit is reversed; drop the leftover change entries so Save is not offered.
                await this.props.record.discard();
            }
            this.state.sel = null;
            this.state.message = _t("Undone.");
        }
    }
}

registry.category("fields").add("agile_workflow_diagram", {
    component: AgileWorkflowDiagram,
    supportedTypes: ["json"],
});
