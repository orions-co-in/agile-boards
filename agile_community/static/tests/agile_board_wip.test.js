import { describe, expect, test } from "@odoo/hoot";
import { makeTestApp, patchWithCleanup } from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import {
    blockedCount,
    cellWip,
    columnFacts,
    lanesKey,
    overLimitMessage,
    readClosedLanes,
    wipState,
    writeClosedLanes,
} from "@agile_community/board/board_helpers";
import { AgileBoardKanbanRenderer } from "@agile_community/board/agile_board_renderer";

describe.current.tags("desktop");

test("a stage without a limit has no badge", async () => {
    await makeTestApp();
    expect(wipState(0, 5)).toBe(null);
    expect(wipState(undefined, 5)).toBe(null);
});

test("the badge says in words whether the stage is under, at or over its limit", async () => {
    await makeTestApp();
    expect(wipState(2, 1)).toEqual({ kind: "ok", icon: "", text: "WIP 1 of 2" });
    expect(wipState(2, 2)).toEqual({ kind: "at", icon: "●", text: "WIP 2 of 2, at the limit" });
    expect(wipState(2, 3)).toEqual({ kind: "over", icon: "▲", text: "WIP 3 of 2, over by 1" });
    expect(wipState(1, 7).text).toBe("WIP 7 of 1, over by 6");
});

test("blocked cards are counted among the loaded records", () => {
    const records = [{ data: { agile_is_blocked: true } }, { data: { agile_is_blocked: false } }, { data: {} }];
    expect(blockedCount(records)).toBe(1);
    expect(blockedCount([])).toBe(0);
});

test("column facts join the stage's counts with the column's blocked cards", async () => {
    await makeTestApp();
    const group = { value: [25, "Review"], list: { records: [{ data: { agile_is_blocked: true } }] } };
    const facts = columnFacts(group, { 25: { limit: 1, current: 2 } });
    expect(facts.blocked).toBe(1);
    expect(facts.wip.kind).toBe("over");
    // The model may give the stage as a plain id, and a stage may have no limit.
    expect(columnFacts({ ...group, value: 26 }, { 25: { limit: 1, current: 2 } }).wip).toBe(null);
    expect(columnFacts(group, undefined).wip).toBe(null);
});

test("sample cards on an empty board do not count as blocked (NU-30)", async () => {
    await makeTestApp();
    const group = {
        value: [25, "Review"],
        model: { useSampleModel: true },
        list: { records: [{ data: { agile_is_blocked: true } }] },
    };
    expect(columnFacts(group, undefined).blocked).toBe(0);
});

test("the over-limit message names the card, the column and that it is only a warning", async () => {
    await makeTestApp();
    const message = overLimitMessage("WALK-3", "Review", wipState(2, 3));
    expect(message).toBe("WALK-3 moved to Review. WIP 3 of 2, over by 1. This is a warning, not a limit.");
});

function fakeRenderer({ stages, fail = false }) {
    const added = [];
    const moves = [];
    const renderer = Object.assign(Object.create(AgileBoardKanbanRenderer.prototype), {
        props: {
            list: {
                context: { default_project_id: 7 },
                groups: [{ id: "g-review", displayName: "Review", list: { records: [] } }],
                moveRecords: async (...args) => moves.push(args),
            },
        },
        orm: {
            call: async () => {
                if (fail) {
                    throw new Error("nope");
                }
                return { stages };
            },
        },
        notification: { add: (message, options) => added.push({ message, options }) },
    });
    const record = { id: "r1", data: { issue_key: "WALK-3", stage_id: [40, "Review"] } };
    renderer.props.list.groups[0].list.records.push(record);
    return { renderer, record, added, moves };
}

test("a drop that leaves the column over its limit warns and offers Undo", async () => {
    await makeTestApp();
    const { renderer, record, added, moves } = fakeRenderer({ stages: [{ stage_id: 40, limit: 2, current: 3 }] });
    await renderer.warnWhenOverLimit(record, "g-progress");
    expect(added).toHaveLength(1);
    expect(added[0].message).toBe("WALK-3 moved to Review. WIP 3 of 2, over by 1. This is a warning, not a limit.");
    expect(added[0].options.type).toBe("warning");
    added[0].options.buttons[0].onClick();
    expect(moves).toEqual([[["r1"], null, "g-progress"]]);
});

test("a drop under or at the limit, or a failed count request, says nothing", async () => {
    await makeTestApp();
    for (const setup of [
        { stages: [{ stage_id: 40, limit: 2, current: 2 }] },
        { stages: [{ stage_id: 99, limit: 1, current: 5 }] },
        { stages: [], fail: true },
    ]) {
        const { renderer, record, added } = fakeRenderer(setup);
        await renderer.warnWhenOverLimit(record, "g-progress");
        expect(added).toHaveLength(0);
    }
});

// ---- remembering folded swimlane rows ----

function fakeStorage(initial = {}) {
    const data = { ...initial };
    return {
        data,
        getItem: (key) => data[key] ?? null,
        setItem: (key, value) => {
            data[key] = value;
        },
        removeItem: (key) => {
            delete data[key];
        },
    };
}

test("folded rows are kept per project and kind of swimlane", () => {
    const key = lanesKey(7, "assignee");
    expect(key).toBe("agile_board_lanes_closed:7:assignee");
    expect(lanesKey(7, "epic")).not.toBe(key);
    expect(lanesKey(8, "assignee")).not.toBe(key);
    const storage = fakeStorage();
    expect(readClosedLanes(storage, key)).toEqual([]);
    writeClosedLanes(storage, key, ["AK", "Unassigned"]);
    expect(readClosedLanes(storage, key)).toEqual(["AK", "Unassigned"]);
    writeClosedLanes(storage, key, []);
    expect(storage.data).toEqual({});
});

test("unreadable or blocked storage means every row starts open", () => {
    const key = lanesKey(7, "epic");
    expect(readClosedLanes(fakeStorage({ [key]: "not json" }), key)).toEqual([]);
    expect(readClosedLanes(fakeStorage({ [key]: '{"a":1}' }), key)).toEqual([]);
    expect(readClosedLanes(fakeStorage({ [key]: '["ok", 3, null]' }), key)).toEqual(["ok"]);
    const blocked = {
        getItem() {
            throw new Error("blocked");
        },
        setItem() {
            throw new Error("blocked");
        },
        removeItem() {
            throw new Error("blocked");
        },
    };
    expect(readClosedLanes(blocked, key)).toEqual([]);
    writeClosedLanes(blocked, key, ["AK"]);
    writeClosedLanes(blocked, key, []);
});

function patchStorage(storage, run) {
    patchWithCleanup(browser, { localStorage: storage });
    run();
}

test("the renderer starts each kind of swimlane with its own folded rows and saves a fold", async () => {
    await makeTestApp();
    const storage = fakeStorage({ [lanesKey(7, "assignee")]: '["AK"]' });
    const renderer = Object.assign(Object.create(AgileBoardKanbanRenderer.prototype), {
        props: { swimlane: "assignee", list: { context: { default_project_id: 7 } } },
        laneState: { collapsed: {}, swimlane: null },
    });
    patchStorage(storage, () => {
        renderer.syncClosedLanes();
        expect(renderer.isCollapsed({ key: "AK" })).toBe(true);
        expect(renderer.isCollapsed({ key: "RM" })).toBe(false);
        renderer.toggleLane({ key: "RM" });
        expect(readClosedLanes(storage, lanesKey(7, "assignee"))).toEqual(["AK", "RM"]);
        renderer.toggleLane({ key: "AK" });
        expect(readClosedLanes(storage, lanesKey(7, "assignee"))).toEqual(["RM"]);
        renderer.props.swimlane = "epic";
        renderer.syncClosedLanes();
        expect(renderer.isCollapsed({ key: "RM" })).toBe(false);
    });
});

test("a per-row limit is counted in each swimlane cell, not across the column", async () => {
    await makeTestApp();
    const group = { value: [4, "In Progress"], list: { records: [{ data: {} }, { data: {} }, { data: {} }] } };
    const wip = { 4: { limit: 2, current: 3, per_swimlane: true } };
    expect(columnFacts(group, wip, false).wip.text).toBe("WIP 3 of 2, over by 1");
    expect(columnFacts(group, wip, true).wip).toEqual({ kind: "row", icon: "", text: "WIP limit 2 in each row" });
    expect(cellWip(group, wip, 2).text).toBe("WIP 2 of 2, at the limit");
    expect(cellWip(group, wip, 3).kind).toBe("over");
    expect(cellWip(group, { 4: { limit: 2, current: 3, per_swimlane: false } }, 3)).toBe(null);
    expect(cellWip(group, {}, 3)).toBe(null);
});
