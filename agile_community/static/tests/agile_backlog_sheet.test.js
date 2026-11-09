import { describe, expect, test } from "@odoo/hoot";
import { makeMockEnv } from "@web/../tests/web_test_helpers";
import { AgileBacklogRenderer } from "@agile_community/backlog/agile_backlog_list";
import { AgileRowSheet } from "@agile_community/backlog/agile_row_sheet";

describe.current.tags("desktop");

function fakeList({ isSmall = true, completed = false, canEdit = true, locked = false } = {}) {
    const calls = { dialogs: [], says: [], moveDialog: 0, editor: [], ranks: [] };
    const row = { dataset: { id: "r1", groupId: "g1" }, querySelector: () => "assignee-cell" };
    const record = { id: "r1" };
    const renderer = Object.assign(Object.create(AgileBacklogRenderer.prototype), {
        uiService: { isSmall },
        dialog: { add: (component, props) => calls.dialogs.push({ component, props }) },
        groupById: () => ({}),
        snapshotRecord: () => ({ key: "WALK-3" }),
        recordFor: () => record,
        isCompletedGroup: () => completed,
        isLockedRecord: () => locked,
        say: (message, options) => calls.says.push([message, options?.type]),
        openMoveDialog: () => calls.moveDialog++,
        openEditor: (...args) => calls.editor.push(args),
        rankByKeyboard: (...args) => calls.ranks.push(args),
    });
    Object.defineProperty(renderer, "canEdit", { value: canEdit });
    return { renderer, row, record, calls };
}

test("a row's menu offers move, assign and rank, and each does what it says", async () => {
    await makeMockEnv();
    const { renderer, row, record, calls } = fakeList();
    renderer.openRowSheet(row);
    const { component, props } = calls.dialogs[0];
    expect(component).toBe(AgileRowSheet);
    expect(props.title).toBe("WALK-3");
    expect(props.actions.map((action) => action.id)).toEqual(["move", "assign", "up", "down"]);
    props.onSelect({ id: "move" });
    props.onSelect({ id: "assign" });
    props.onSelect({ id: "up" });
    props.onSelect({ id: "down" });
    expect(calls.moveDialog).toBe(1);
    expect(calls.editor).toEqual([[record, "user_ids", "assignee-cell"]]);
    expect(calls.ranks).toEqual([[row, -1], [row, 1]]);
});

test("without edit rights the menu has no Assign, and completed sprints say so instead", async () => {
    await makeMockEnv();
    const noEdit = fakeList({ canEdit: false });
    noEdit.renderer.openRowSheet(noEdit.row);
    expect(noEdit.calls.dialogs[0].props.actions.map((action) => action.id)).toEqual(["move", "up", "down"]);
    const done = fakeList({ completed: true });
    done.renderer.openRowSheet(done.row);
    expect(done.calls.dialogs).toHaveLength(0);
    expect(done.calls.says).toEqual([["Issues in completed sprints cannot be changed here.", "warning"]]);
});

test("on a phone the handle cell opens the menu; on a wide screen it is left to drag", async () => {
    await makeMockEnv();
    const phone = fakeList();
    const cell = { closest: () => phone.row };
    const ev = { target: { closest: () => cell }, button: 0, preventDefault() {}, stopPropagation() {} };
    phone.renderer.onBacklogClick(ev);
    expect(phone.calls.dialogs).toHaveLength(1);
    const wide = fakeList({ isSmall: false, canEdit: false });
    wide.renderer.onBacklogClick(ev);
    expect(wide.calls.dialogs).toHaveLength(0);
});
