import { describe, expect, test } from "@odoo/hoot";
import { press, queryAllTexts, queryOne, waitFor } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { MainComponentsContainer } from "@web/core/main_components_container";
import {
    contains,
    sortableDrag,
    defineModels,
    fields,
    models,
    mountView,
    mountWithCleanup,
    onRpc,
} from "@web/../tests/web_test_helpers";
import "@agile_community/backlog/agile_backlog_list";

describe.current.tags("desktop");

const sprint = (extra) => ({
    id: 1,
    name: "Planned",
    state: "draft",
    date_start: "2026-11-02",
    date_end: "2026-11-15",
    goal: "",
    planned_points: 8,
    capacity_points: 0,
    over_capacity: false,
    planning_confirmed: true,
    planning_stale: false,
    unestimated_count: 0,
    points_by_status: {},
    completed_points: 0,
    committed_points_at_close: 0,
    can_manage: true,
    ...extra,
});

const SPRINTS = [
    sprint({ id: 1, name: "Planned" }),
    sprint({ id: 2, name: "Active", state: "in_progress", date_start: "2026-10-20" }),
    sprint({ id: 3, name: "Closed", state: "done", date_start: "2026-10-01" }),
];

class ProjectSprint extends models.Model {
    _name = "project.sprint";
    name = fields.Char();
    _records = SPRINTS.map(({ id, name }) => ({ id, name }));
}

class ProjectTask extends models.Model {
    _name = "project.task";
    name = fields.Char();
    issue_key = fields.Char();
    sequence = fields.Integer();
    sprint_id = fields.Many2one({ relation: "project.sprint" });
    _records = [
        { id: 1, name: "One", issue_key: "WALK-1", sequence: 1, sprint_id: 1 },
        { id: 2, name: "Two", issue_key: "WALK-2", sequence: 2, sprint_id: 1 },
        { id: 3, name: "Three", issue_key: "WALK-3", sequence: 3, sprint_id: 2 },
        { id: 4, name: "Four", issue_key: "WALK-4", sequence: 4, sprint_id: false },
        { id: 5, name: "Five", issue_key: "WALK-5", sequence: 5, sprint_id: 3 },
    ];
}

class ProjectProject extends models.Model {
    _name = "project.project";
    name = fields.Char();
}

defineMailModels();
defineModels([ProjectSprint, ProjectTask, ProjectProject]);

async function mountBacklog({ sprints = SPRINTS } = {}) {
    onRpc("project.project", "agile_backlog_sprints", () => ({
        project_id: 7,
        sprints,
        backlog: { issue_count: 1, unestimated_count: 0 },
    }));
    await mountWithCleanup(MainComponentsContainer);
    await mountView({
        type: "list",
        resModel: "project.task",
        context: { default_project_id: 7 },
        groupBy: ["sprint_id"],
        arch: `<list js_class="agile_backlog_list" expand="1" default_order="sequence, id">
                    <field name="sequence" widget="handle"/>
                    <field name="issue_key"/>
                    <field name="name"/>
                    <field name="sprint_id" column_invisible="1"/>
                </list>`,
    });
    await animationFrame();
    // Odoo opens as many groups as fit the first page of rows; open every group here.
    for (const header of document.querySelectorAll(".o_group_header:not(.o_group_open)")) {
        await contains(header).click();
    }
    await animationFrame();
}

// WALK-5 sits in the completed sprint and never moves; leave it out of the order checks.
const keys = () => queryAllTexts(".o_data_row td[name=issue_key]").filter((key) => key !== "WALK-5");
const toast = () => queryAllTexts(".o_notification_content");
const row = (key) => `.o_data_row:contains(${key})`;

/** Drags a row's handle to another row the way the sortable list reads it: from the top edge of the dragged row. */
async function dragRow(key, target, how) {
    const drag = await sortableDrag(`${row(key)} .o_handle_cell`);
    await drag[how](target);
    await drag.drop();
}

async function focusCell(key) {
    queryOne(`${row(key)} td[name=issue_key]`).focus();
    await animationFrame();
}

test("dragging a row inside its sprint ranks it, says where it landed and Undo puts it back", async () => {
    const resequenced = [];
    onRpc("project.task", "web_resequence", ({ args }) => {
        resequenced.push(args[0]);
    });
    await mountBacklog();
    expect(keys()).toEqual(["WALK-1", "WALK-2", "WALK-3", "WALK-4"]);
    await dragRow("WALK-1", row("WALK-2"), "moveUnder");
    await animationFrame();
    expect(keys()).toEqual(["WALK-2", "WALK-1", "WALK-3", "WALK-4"]);
    expect(resequenced.length).toBe(1);
    expect(toast()).toEqual(["WALK-1 is now 2 of 2 in Planned."]);
    expect(".o_ag_live").toHaveText("WALK-1 is now 2 of 2 in Planned.");
    await contains(".o_notification button:contains(Undo)").click();
    await animationFrame();
    expect(keys()).toEqual(["WALK-1", "WALK-2", "WALK-3", "WALK-4"]);
    expect(".o_ag_live").toHaveText("Move undone.");
});

test("dragging into a confirmed planned sprint says the plan changed, and into the active sprint says scope changed", async () => {
    const saves = [];
    onRpc("project.task", "web_save", ({ args }) => {
        saves.push(args);
    });
    await mountBacklog();
    await dragRow("WALK-4", row("WALK-2"), "moveAbove");
    await animationFrame();
    expect(toast().at(-1)).toBe(
        "WALK-4 added to Planned. The confirmed plan changed: update it before starting."
    );
    expect(saves.length).toBe(1);
    expect(saves[0][1]).toEqual({ sprint_id: 1 });
    await dragRow("WALK-4", row("WALK-3"), "moveAbove");
    await animationFrame();
    expect(toast().at(-1)).toBe(
        "WALK-4 added to Active. It counts as a scope change on the Pulse. The confirmed plan of Planned changed: update it before starting."
    );
});

test("moving out of a sprint to the Backlog is worded and Undo restores the old sprint", async () => {
    const saves = [];
    onRpc("project.task", "web_save", ({ args }) => {
        saves.push(args[1]);
    });
    await mountBacklog();
    await dragRow("WALK-3", row("WALK-4"), "moveUnder");
    await animationFrame();
    expect(toast().at(-1)).toBe(
        "WALK-3 moved to Backlog. It counts as a scope change on the Pulse."
    );
    expect(saves).toEqual([{ sprint_id: false }]);
    await contains(".o_notification button:contains(Undo)").click();
    await animationFrame();
    expect(saves.at(-1)).toEqual({ sprint_id: 2 });
});

test("a refused move snaps back and shows the server's reason", async () => {
    onRpc("project.task", "web_save", () => {
        throw new Error("Only this project's Agile Manager can change sprint membership.");
    });
    await mountBacklog();
    await dragRow("WALK-4", row("WALK-2"), "moveAbove");
    await animationFrame();
    expect(toast().at(-1)).toBe(
        "Could not move WALK-4: Only this project's Agile Manager can change sprint membership."
    );
    expect(".o_notification_content").toHaveCount(1);
    expect(keys()).toEqual(["WALK-1", "WALK-2", "WALK-3", "WALK-4"]);
});

test("completed sprints have no handle and refuse a drop", async () => {
    const saves = [];
    onRpc("project.task", "web_save", ({ args }) => {
        saves.push(args);
    });
    await mountBacklog();
    expect(`${row("WALK-5")}`).toHaveClass("o_ag_row_locked");
    expect(`${row("WALK-5")}`).not.toHaveClass("o_row_draggable");
    expect(`${row("WALK-1")}`).toHaveClass("o_row_draggable");
    // Dropping on a completed sprint's row is ignored by the list; dropping on its header is refused.
    await dragRow("WALK-4", row("WALK-5"), "moveUnder");
    await animationFrame();
    expect(saves.length).toBe(0);
    await dragRow("WALK-4", ".o_group_header:contains(Closed)", "moveTo");
    await animationFrame();
    expect(toast().at(-1)).toBe(
        "Completed sprints cannot take issues here. Use the sprint's Correct action."
    );
    expect(saves.length).toBe(0);
});

// A configurator for the next test: this one waits on several rank requests, so it gets a longer limit.
test.timeout(20000);
test("Alt+Down and Alt+Up rank the focused row and the edges say so", async () => {
    await mountBacklog();
    // Each step waits for its visible result, not a fixed number of frames, so a slow run still passes.
    const lastToast = async (text) => {
        await waitFor(`.o_notification_content:contains("${text}")`, { timeout: 5000 });
        expect(toast().at(-1)).toBe(text);
    };
    await focusCell("WALK-1");
    await press(["alt", "ArrowDown"]);
    await lastToast("WALK-1 is now 2 of 2 in Planned.");
    expect(keys().slice(0, 2)).toEqual(["WALK-2", "WALK-1"]);
    await focusCell("WALK-1");
    await press(["alt", "ArrowDown"]);
    await lastToast("WALK-1 is already last in Planned.");
    await focusCell("WALK-1");
    await press(["alt", "ArrowUp"]);
    await lastToast("WALK-1 is now 1 of 2 in Planned.");
    expect(keys().slice(0, 2)).toEqual(["WALK-1", "WALK-2"]);
    await focusCell("WALK-1");
    await press(["alt", "ArrowUp"]);
    await lastToast("WALK-1 is already first in Planned.");
});

test("m opens the Move to menu and choosing a sprint moves the issue", async () => {
    const saves = [];
    onRpc("project.task", "web_save", ({ args }) => {
        saves.push(args[1]);
    });
    await mountBacklog();
    await focusCell("WALK-4");
    await press("m");
    await waitFor(".o_ag_move_targets");
    expect(queryAllTexts(".o_ag_move_targets button")).toEqual([
        "Active (active)",
        "Planned",
        "Top of Backlog",
    ]);
    await contains(".o_ag_move_targets button:contains(Planned)").click();
    await animationFrame();
    expect(saves).toEqual([{ sprint_id: 1 }]);
    expect(toast().at(-1)).toBe(
        "WALK-4 added to Planned. The confirmed plan changed: update it before starting."
    );
});

test("rows in a completed sprint refuse keyboard moves with a plain message", async () => {
    await mountBacklog();
    await focusCell("WALK-5");
    await press(["alt", "ArrowDown"]);
    await animationFrame();
    expect(toast().at(-1)).toBe("Issues in completed sprints cannot be reordered.");
    await press("m");
    await animationFrame();
    expect(".o_ag_move_targets").toHaveCount(0);
});
