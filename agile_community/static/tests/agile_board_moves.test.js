import { describe, expect, test } from "@odoo/hoot";
import { animationFrame, queryAllTexts } from "@odoo/hoot-dom";
import { contains, defineModels, fields, makeMockEnv, mountView, onRpc } from "@web/../tests/web_test_helpers";
import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { projectModels } from "@project/../tests/project_models";
import { AgileBoardKanbanRenderer } from "@agile_community/board/agile_board_renderer";
import {
    edgeMessage,
    movedMessage,
    neighbourGroup,
    otherRowMessage,
    reasonOf,
    refusedMessage,
} from "@agile_community/board/board_moves";

describe.current.tags("desktop");

// The project test models plus the Agile fields the board reads.
class AgileProjectTask extends projectModels.ProjectTask {
    issue_key = fields.Char();
    agile_lane_assignee = fields.Char();
    agile_lane_epic = fields.Char();
    agile_is_blocked = fields.Boolean();
    story_points = fields.Float();
    story_points_estimated = fields.Boolean();
}
defineMailModels();
defineModels({ ...projectModels, ProjectTask: AgileProjectTask });

// ---- the words ----

test("move messages name the card and say what to do", async () => {
    await makeMockEnv();
    expect(movedMessage("WALK-3", "Review")).toBe("WALK-3 moved to Review.");
    expect(refusedMessage("WALK-3", "Add an assignee.")).toBe("WALK-3 was not moved. Add an assignee.");
    expect(refusedMessage("WALK-3", "")).toBe("WALK-3 was not moved.");
    expect(otherRowMessage("WALK-3", "AK", "assignee")).toBe(
        "WALK-3 stays in AK. Open the issue to change the assignee."
    );
    expect(otherRowMessage("WALK-3", "Search", "epic")).toBe(
        "WALK-3 stays in Search. Open the issue to change the epic."
    );
    expect(edgeMessage("WALK-3", -1)).toBe("WALK-3 is already in the first column.");
    expect(edgeMessage("WALK-3", 1)).toBe("WALK-3 is already in the last column.");
    expect(reasonOf({ data: { message: "Server says no" } })).toBe("Server says no");
    expect(reasonOf(new Error("boom"))).toBe("boom");
});

test("the next column skips folded ones and stops at the edges", () => {
    const a = { isFolded: false };
    const b = { isFolded: true };
    const c = { isFolded: false };
    const groups = [a, b, c];
    expect(neighbourGroup(groups, a, 1)).toBe(c);
    expect(neighbourGroup(groups, c, -1)).toBe(a);
    expect(neighbourGroup(groups, a, -1)).toBe(null);
    expect(neighbourGroup(groups, c, 1)).toBe(null);
    expect(neighbourGroup(groups, b, 1)).toBe(null);
});

// ---- the renderer's rules, without a view ----

function fakeBoard({ moveFails = null, swimlane = "assignee" } = {}) {
    const calls = { moves: [], notes: [], rpc: 0 };
    const stages = [
        { id: "g1", isFolded: false, displayName: "Backlog", list: { records: [] } },
        { id: "g2", isFolded: false, displayName: "Ready", list: { records: [] } },
        { id: "g3", isFolded: false, displayName: "Review", list: { records: [] } },
    ];
    const record = { id: "r1", data: { issue_key: "WALK-3", stage_id: [1, "Backlog"] } };
    stages[0].list.records.push(record);
    const renderer = Object.assign(Object.create(AgileBoardKanbanRenderer.prototype), {
        props: {
            swimlane,
            list: {
                isGrouped: true,
                context: { default_project_id: 7 },
                groups: stages,
                records: [record],
                moveRecord: async (...args) => {
                    if (moveFails) {
                        throw moveFails;
                    }
                    calls.moves.push(args);
                    stages[0].list.records.splice(0, 1);
                    stages[1].list.records.push(record);
                },
            },
        },
        orm: { call: async () => ({ stages: [] }) },
        notification: { add: (message, options) => calls.notes.push([message, options.type]) },
        toggleProcessing() {},
        focusCard() {},
    });
    Object.defineProperty(renderer, "canMoveRecords", { value: true });
    return { renderer, record, stages, calls };
}

const cell = (id, lane) => ({ dataset: { id, lane } });

test("a sideways drop inside the row moves the card", async () => {
    await makeMockEnv();
    const { renderer, calls } = fakeBoard();
    await renderer.dropOnLane("r1", "g1", cell("g2", "AK"), cell("g1", "AK"));
    expect(calls.moves).toEqual([["r1", "g1", null, "g2"]]);
    expect(calls.notes).toEqual([]);
});

test("a drop on another row is refused with a message and nothing moves", async () => {
    await makeMockEnv();
    const { renderer, calls } = fakeBoard();
    await renderer.dropOnLane("r1", "g1", cell("g2", "RM"), cell("g1", "AK"));
    expect(calls.moves).toEqual([]);
    expect(calls.notes).toEqual([["WALK-3 stays in AK. Open the issue to change the assignee.", "warning"]]);
    // Rows of one column share a group id, so the row decides, not the column.
    const same = fakeBoard();
    await same.renderer.dropOnLane("r1", "g1", cell("g1", "RM"), cell("g1", "AK"));
    expect(same.calls.notes).toHaveLength(1);
});

test("a drop back into the same cell does nothing", async () => {
    await makeMockEnv();
    const { renderer, calls } = fakeBoard();
    await renderer.dropOnLane("r1", "g1", cell("g1", "AK"), cell("g1", "AK"));
    expect(calls.moves).toEqual([]);
    expect(calls.notes).toEqual([]);
});

test("a move the server refuses is worded with its reason and reports failure", async () => {
    await makeMockEnv();
    const error = { data: { message: "Before moving this issue to In Progress, add an assignee." } };
    const { renderer, record, calls } = fakeBoard({ moveFails: error });
    const moved = await renderer.moveCard(record, "g1", "g2");
    expect(moved).toBe(false);
    expect(calls.notes).toEqual([
        ["WALK-3 was not moved. Before moving this issue to In Progress, add an assignee.", "danger"],
    ]);
});

function key(ev) {
    return Object.assign(
        {
            altKey: true,
            preventDefault() {
                this.prevented = true;
            },
            target: { closest: () => ({ dataset: { id: "r1" }, closest: () => ({ dataset: { id: "r1" } }) }) },
        },
        ev
    );
}

test("Alt+Right moves the focused card one column and announces it", async () => {
    await makeMockEnv();
    const { renderer, calls } = fakeBoard();
    const ev = key({ key: "ArrowRight" });
    await renderer.onCardKeydown(ev);
    expect(ev.prevented).toBe(true);
    expect(calls.moves).toEqual([["r1", "g1", null, "g2"]]);
    expect(calls.notes).toEqual([["WALK-3 moved to Ready.", "info"]]);
});

test("Alt+Left at the first column says so; keys without Alt are left alone", async () => {
    await makeMockEnv();
    const { renderer, calls } = fakeBoard();
    await renderer.onCardKeydown(key({ key: "ArrowLeft" }));
    expect(calls.moves).toEqual([]);
    expect(calls.notes).toEqual([["WALK-3 is already in the first column.", "info"]]);
    const plain = key({ key: "ArrowRight", altKey: false });
    await renderer.onCardKeydown(plain);
    expect(plain.prevented).toBe(undefined);
    expect(calls.moves).toEqual([]);
});

test("a refused keyboard move stays put and says why", async () => {
    await makeMockEnv();
    const { renderer, calls } = fakeBoard({ moveFails: { data: { message: "No." } } });
    await renderer.onCardKeydown(key({ key: "ArrowRight" }));
    expect(calls.notes).toEqual([["WALK-3 was not moved. No.", "danger"]]);
});

// ---- a real pointer drag in a mounted board ----

test("dragging a card sideways inside its swimlane moves it; dropping it on another row does not", async () => {
    const Task = AgileProjectTask;
    Task._records = [
        { id: 1, name: "One", issue_key: "WALK-1", project_id: 1, stage_id: 1, agile_lane_assignee: "AK" },
        { id: 2, name: "Two", issue_key: "WALK-2", project_id: 1, stage_id: 1, agile_lane_assignee: "RM" },
        // A card in the second column, so that the column exists.
        { id: 3, name: "Three", issue_key: "WALK-3", project_id: 1, stage_id: 2, agile_lane_assignee: "RM" },
    ];
    Task._views.kanban = `
        <kanban default_group_by="stage_id" js_class="agile_board_kanban">
            <field name="issue_key"/><field name="agile_lane_assignee"/><field name="agile_lane_epic"/>
            <field name="agile_is_blocked"/><field name="story_points"/><field name="story_points_estimated"/>
            <templates><t t-name="card"><field name="name"/></t></templates>
        </kanban>`;
    const writes = [];
    onRpc("project.project", "agile_pulse_data", () => ({ state: "kanban", sprint: false, days: [] }));
    onRpc("project.project", "agile_board_options", () => ({
        project_id: 1, swimlane: "assignee", filters: [], task_types: [], epics: [],
    }));
    onRpc("project.project", "agile_board_wip", () => ({ project_id: 1, stages: [] }));
    onRpc("project.task", "web_save", ({ args }) => {
        writes.push(args);
    });
    await mountView({
        type: "kanban",
        resModel: "project.task",
        context: { default_project_id: 1, agile_swimlane: "assignee" },
    });
    await animationFrame();
    expect(".o_ag_swimlanes .o_ag_lane").toHaveCount(2);
    expect(".o_ag_lane_head .o_ag_lane_col").toHaveCount(2);
    expect(queryAllTexts(".o_ag_lane_title b")).toEqual(["AK", "RM"]);
    const target = ".o_ag_lane[data-lane='AK'] .o_ag_lane_cell:eq(1)";
    expect(".o_ag_lane[data-lane='AK'] .o_ag_lane_item").toHaveCount(1);
    // Dropping on the other row's cell of the same column is refused.
    const drag = await contains(".o_ag_lane[data-lane='AK'] .o_ag_lane_item").drag();
    await drag.moveTo(".o_ag_lane[data-lane='RM'] .o_ag_lane_cell:eq(1)");
    await drag.drop();
    await animationFrame();
    expect(writes).toHaveLength(0);
    expect(".o_ag_lane[data-lane='AK'] .o_ag_lane_cell:eq(0) .o_ag_lane_item").toHaveCount(1);
    // Dropping sideways in the same row moves it.
    const drag2 = await contains(".o_ag_lane[data-lane='AK'] .o_ag_lane_item").drag();
    await drag2.moveTo(target);
    await drag2.drop();
    await animationFrame();
    await animationFrame();
    expect(writes).toHaveLength(1);
    expect(writes[0][0]).toEqual([1]);
    expect(writes[0][1]).toEqual({ stage_id: 2 });
    expect(".o_ag_lane[data-lane='AK'] .o_ag_lane_cell:eq(1) .o_ag_lane_item").toHaveCount(1);
});

// ---- phone: column tabs and the Move-to sheet ----

function phoneBoard({ moves = [], isSmall = true } = {}) {
    const board = fakeBoard();
    board.stages.forEach((stage, index) => (stage.value = index + 1));
    Object.assign(board.renderer, {
        env: { isSmall },
        tabState: { id: null },
        sheet: { recordId: null, title: "", moves: [], loading: false, groupId: null },
        sheetRef: { el: null },
        getGroupUnloadedCount: () => 0,
        columnFacts: () => ({ wip: null }),
        orm: { call: async (model, method) => (method === "agile_allowed_moves" ? moves : { stages: [] }) },
    });
    return board;
}

test("on a phone each column is a tab with its count, and the first one is open", async () => {
    await makeMockEnv();
    const { renderer } = phoneBoard();
    expect(renderer.phoneTabs.map((tab) => [tab.name, tab.count, tab.active])).toEqual([
        ["Backlog", 1, true],
        ["Ready", 0, false],
        ["Review", 0, false],
    ]);
    renderer.selectTab("g3");
    expect(renderer.phoneTabs.map((tab) => tab.active)).toEqual([false, false, true]);
    // A tab whose column has gone falls back to the first.
    renderer.selectTab("gone");
    expect(renderer.activeTabId).toBe("g1");
});

test("a wide screen has no tabs", async () => {
    await makeMockEnv();
    expect(phoneBoard({ isSmall: false }).renderer.phoneTabs).toBe(null);
});

test("Move to opens a sheet of the moves the server allows and a choice moves the card", async () => {
    await makeMockEnv();
    const { renderer, record, calls } = phoneBoard({
        moves: [{ name: "Mark ready", stage_id: 2, stage: "Ready" }],
    });
    record.resId = 11;
    const link = { closest: (selector) => (selector === ".o_ag_move_to" ? link : { dataset: { id: "r1" } }) };
    const ev = { target: link, preventDefault() {} };
    await renderer.onMoveToClick(ev);
    expect(renderer.sheet.title).toBe("Move WALK-3");
    expect(renderer.sheet.moves).toEqual([{ name: "Mark ready", stage_id: 2, stage: "Ready" }]);
    expect(renderer.sheet.loading).toBe(false);
    await renderer.chooseMove(renderer.sheet.moves[0]);
    expect(calls.moves).toEqual([["r1", "g1", null, "g2"]]);
    expect(calls.notes).toEqual([["WALK-3 moved to Ready.", "info"]]);
    expect(renderer.sheet.recordId).toBe(null);
});

test("a click elsewhere on the board does not open the sheet, and Close leaves the card alone", async () => {
    await makeMockEnv();
    const { renderer, calls } = phoneBoard();
    await renderer.onMoveToClick({ target: { closest: () => null }, preventDefault() {} });
    expect(renderer.sheet.recordId).toBe(null);
    renderer.sheet.recordId = "r1";
    renderer.closeSheet();
    expect(renderer.sheet.recordId).toBe(null);
    expect(calls.moves).toEqual([]);
});

test("closing the sheet gives focus back to the Move to button that opened it", async () => {
    await makeMockEnv();
    const { renderer, record } = phoneBoard({ moves: [] });
    record.resId = 11;
    let focused = 0;
    const link = {
        isConnected: true,
        focus: () => focused++,
        closest: (selector) => (selector === ".o_ag_move_to" ? link : { dataset: { id: "r1" } }),
    };
    await renderer.onMoveToClick({ target: link, preventDefault() {} });
    renderer.closeSheet();
    await new Promise((resolve) => setTimeout(resolve, 5));
    expect(focused).toBe(1);
    // A button that left the page (the card moved away) is not focused.
    link.isConnected = false;
    await renderer.onMoveToClick({ target: link, preventDefault() {} });
    renderer.closeSheet();
    await new Promise((resolve) => setTimeout(resolve, 5));
    expect(focused).toBe(1);
});
