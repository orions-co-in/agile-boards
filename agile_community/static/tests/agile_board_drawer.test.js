import { describe, expect, test } from "@odoo/hoot";
import { click, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { contains, defineModels, fields, makeTestApp, models, mountWithCleanup, onRpc } from "@web/../tests/web_test_helpers";
import { AgileCardDrawer } from "@agile_community/board/agile_card_drawer";
import { AgileBoardKanbanController } from "@agile_community/board/agile_board_kanban";

describe.current.tags("desktop");

class ProjectTask extends models.Model {
    _name = "project.task";
    name = fields.Char({ required: true });
    _records = [{ id: 5, name: "Pulse C" }];
    _views = {
        "form,12": `<form><sheet><group><field name="name"/></group></sheet></form>`,
    };
}

defineMailModels();
defineModels([ProjectTask]);

async function mountDrawer(overrides = {}) {
    const calls = { closed: 0, expanded: [], leave: null };
    await makeTestApp();
    await mountWithCleanup(AgileCardDrawer, {
        props: {
            resId: 5,
            viewId: 12,
            register: (leave) => (calls.leave = leave),
            onClose: () => calls.closed++,
            onExpand: (id) => calls.expanded.push(id),
            ...overrides,
        },
    });
    await animationFrame();
    await animationFrame();
    return calls;
}

test("the drawer shows the issue form next to the board and a Done button", async () => {
    await mountDrawer();
    expect(".o_ag_drawer").toHaveCount(1);
    expect(".o_ag_drawer .o_form_view").toHaveCount(1);
    expect(".o_ag_drawer [name=name] input").toHaveValue("Pulse C");
    expect(".o_ag_drawer_close").toHaveText("Done");
    expect(".o_ag_drawer").toHaveAttribute("aria-label", "Issue details");
});

test("Done saves pending changes before it closes", async () => {
    const saved = [];
    onRpc("project.task", "web_save", ({ args }) => {
        saved.push(args[1]);
    });
    const calls = await mountDrawer();
    await contains(".o_ag_drawer [name=name] input").edit("Pulse C, renamed");
    await click(".o_ag_drawer_close");
    await animationFrame();
    await animationFrame();
    expect(calls.closed).toBe(1);
    expect(saved).toEqual([{ name: "Pulse C, renamed" }]);
});

test("a change that cannot be saved keeps the drawer open", async () => {
    const calls = await mountDrawer();
    await contains(".o_ag_drawer [name=name] input").edit("");
    await click(".o_ag_drawer_close");
    await animationFrame();
    await animationFrame();
    expect(calls.closed).toBe(0);
    expect(".o_ag_drawer").toHaveCount(1);
});

test("Escape closes the drawer, but not while a menu is open", async () => {
    const calls = await mountDrawer();
    const menu = document.createElement("div");
    menu.className = "o-dropdown--menu";
    document.body.append(menu);
    queryOne(".o_ag_drawer").dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    await animationFrame();
    await animationFrame();
    expect(calls.closed).toBe(0);
    menu.remove();
    queryOne(".o_ag_drawer").dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    await animationFrame();
    await animationFrame();
    expect(calls.closed).toBe(1);
});

test("Open full page leaves through the same save and hands over the issue", async () => {
    const calls = await mountDrawer();
    await click(".o_ag_drawer_expand");
    await animationFrame();
    await animationFrame();
    expect(calls.expanded).toEqual([5]);
    expect(calls.closed).toBe(0);
});

test("the board registers a leave function so another card can be opened safely", async () => {
    const calls = await mountDrawer();
    expect(typeof calls.leave).toBe("function");
    expect(await calls.leave()).toBe(true);
});

function fakeBoard(overrides = {}) {
    const opened = [];
    // Keep the controller's getters (drawerViewId) by building on its prototype.
    const board = Object.assign(Object.create(AgileBoardKanbanController.prototype), {
        env: { isSmall: false },
        props: {
            context: { agile_drawer_view_id: 12 },
            selectRecord: (id, options) => opened.push(["page", id, options.activeIds]),
        },
        model: { root: { records: [{ resId: 5 }, { resId: 6 }] }, load: async () => opened.push(["reload"]) },
        drawer: { resId: null },
        drawerLeave: null,
        ...overrides,
    });
    return { board, opened };
}

const record = (resId) => ({ resId, data: { issue_key: `WALK-${resId}` } });

test("a card click opens the drawer, on a phone too; new-window clicks and boards without the drawer use the form page", async () => {
    let { board, opened } = fakeBoard();
    await AgileBoardKanbanController.prototype.openRecord.call(board, record(5));
    expect(board.drawer.resId).toBe(5);
    expect(opened).toEqual([]);

    ({ board, opened } = fakeBoard({ env: { isSmall: true } }));
    await AgileBoardKanbanController.prototype.openRecord.call(board, record(5));
    expect(board.drawer.resId).toBe(5);
    expect(opened).toEqual([]);

    ({ board, opened } = fakeBoard());
    await AgileBoardKanbanController.prototype.openRecord.call(board, record(5), { newWindow: true });
    expect(board.drawer.resId).toBe(null);
    expect(opened).toEqual([["page", 5, [5, 6]]]);

    ({ board, opened } = fakeBoard({ props: { context: {}, selectRecord: (id, o) => opened.push(["page", id, o.activeIds]) } }));
    await AgileBoardKanbanController.prototype.openRecord.call(board, record(5));
    expect(board.drawer.resId).toBe(null);
    expect(opened).toEqual([["page", 5, [5, 6]]]);
});

test("opening another card saves the open one first and stays put when that fails", async () => {
    let { board, opened } = fakeBoard({ drawer: { resId: 5 }, drawerLeave: async () => true });
    await AgileBoardKanbanController.prototype.openRecord.call(board, record(6));
    expect(board.drawer.resId).toBe(6);
    expect(opened).toEqual([["reload"]]);

    ({ board, opened } = fakeBoard({ drawer: { resId: 5 }, drawerLeave: async () => false }));
    await AgileBoardKanbanController.prototype.openRecord.call(board, record(6));
    expect(board.drawer.resId).toBe(5);
    expect(opened).toEqual([]);
});
