import { describe, expect, test } from "@odoo/hoot";
import { makeTestApp } from "@web/../tests/web_test_helpers";
import { buildModel, hasMove, recordKey, reorder, sequencesFor } from "@agile_community/workflow/workflow_canvas_helpers";
import { CATEGORY_CHOICES, arrowLabel, flowLayout } from "@agile_community/workflow/agile_workflow_diagram";

describe.current.tags("desktop");

const status = (resId, name, category, sequence, count = 0) => ({
    resId,
    _virtualId: false,
    data: { sequence, stage_id: { id: resId * 10, display_name: name }, category, issue_count: count },
});
const move = (resId, name, from, to, flags = {}) => ({
    resId,
    _virtualId: false,
    data: {
        name,
        from_status_id: { id: from, display_name: "x" },
        to_status_id: { id: to, display_name: "y" },
        allow_contributor: false,
        allow_reviewer: false,
        allow_manager: true,
        ...flags,
    },
});

test("the model reads the lists in sequence order, with roles in words", () => {
    const model = buildModel(
        [status(2, "To Do", "ready", 20), status(1, "Backlog", "backlog", 10, 3)],
        [move(7, "Plan into sprint", 1, 2, { allow_contributor: true })]
    );
    expect(model.statuses.map((s) => s.name)).toEqual(["Backlog", "To Do"]);
    expect(model.statuses[0].count).toBe(3);
    expect(model.moves[0]).toInclude("id");
    expect(model.moves[0].roles).toEqual(["Contributors", "Managers"]);
    expect([model.moves[0].from, model.moves[0].to]).toEqual([1, 2]);
});

test("a renamed status shows its new name before the form is saved", () => {
    const renamed = status(1, "In QA", "review", 10);
    renamed.data.name = "QA check";
    expect(buildModel([renamed], []).statuses[0].name).toBe("QA check");
});

test("a hidden status is flagged and a never-used one can be deleted", () => {
    const hidden = status(1, "In QA", "review", 10);
    Object.assign(hidden.data, { stage_active: false, can_delete: true });
    const shown = status(2, "Done", "done", 20);
    Object.assign(shown.data, { stage_active: true, can_delete: false });
    const model = buildModel([hidden, shown], []);
    expect(model.statuses.map((s) => [s.hidden, s.canDelete])).toEqual([[true, true], [false, false]]);
});

test("a move with conditions says how many in its arrow label and reads them in the model", async () => {
    await makeTestApp();
    const model = buildModel(
        [status(1, "Review", "review", 10), status(2, "Done", "done", 20)],
        [move(5, "Complete", 1, 2, { require_no_open_subtasks: true, require_not_blocked: true })]
    );
    expect(model.moves[0].conditions).toEqual(["all sub-issues done or canceled", "the issue not blocked"]);
    expect(arrowLabel(model.moves[0], false)).toBe("Complete (2 rules)");
    expect(arrowLabel({ name: "Cancel", conditions: ["x"] }, true)).toBe("Cancel (managers, 1 rule)");
    expect(arrowLabel({ name: "Start", conditions: [] }, false)).toBe("Start");
});

test("the Add status panel offers the six categories in flow order, each with its meaning", async () => {
    await makeTestApp();
    expect(CATEGORY_CHOICES.map((choice) => choice.value)).toEqual([
        "backlog", "ready", "progress", "review", "done", "canceled",
    ]);
    expect(CATEGORY_CHOICES.every((choice) => String(choice.hint).length > 0)).toBe(true);
});

test("a line without both ends is not drawn", () => {
    const half = move(8, "Half", 1, 2);
    half.data.to_status_id = false;
    expect(buildModel([status(1, "Backlog", "backlog", 10)], [half]).moves).toHaveLength(0);
});

test("an unsaved line is known by its virtual id", () => {
    expect(recordKey({ resId: false, _virtualId: "virtual_3" })).toBe("virtual_3");
    expect(recordKey({ resId: 5, _virtualId: false })).toBe(5);
});

test("dragging a status moves it to the target position", () => {
    expect(reorder([1, 2, 3, 4], 2, 3)).toEqual([1, 3, 4, 2]);
    expect(reorder([1, 2, 3, 4], 4, 0)).toEqual([4, 1, 2, 3]);
    expect(reorder([1, 2, 3], 9, 1)).toEqual([1, 2, 3]);
    expect(reorder([1, 2, 3], 1, 99)).toEqual([2, 3, 1]);
});

test("sequences leave room between statuses", () => {
    expect(sequencesFor([5, 3, 9])).toEqual({ 5: 10, 3: 20, 9: 30 });
});

test("a status pair has one move", () => {
    const moves = [{ from: 1, to: 2 }];
    expect(hasMove(moves, 1, 2)).toBe(true);
    expect(hasMove(moves, 2, 1)).toBe(false);
});

test("each box gets a dot under it and each arrow keeps its id", async () => {
    await makeTestApp();
    const flow = flowLayout({
        statuses: [
            { stage_id: 1, name: "Backlog", category: "backlog", count: 0 },
            { stage_id: 2, name: "To Do", category: "ready", count: 0 },
        ],
        moves: [{ id: 42, name: "Plan", from: 1, to: 2, roles: ["Managers"] }],
    });
    expect(flow.boxes.map((b) => b.portY > b.y + b.h)).toEqual([true, true]);
    expect(flow.boxes[0].portX).toBe(flow.boxes[0].x + flow.boxes[0].w / 2);
    expect(flow.arrows[0].id).toBe(42);
});
