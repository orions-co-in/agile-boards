import { describe, expect, test } from "@odoo/hoot";
import { click, fill, press, queryAllTexts, queryOne, waitFor } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { MainComponentsContainer } from "@web/core/main_components_container";
import {
    contains,
    defineModels,
    fields,
    models,
    mountView,
    mockService,
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
    planning_confirmed: false,
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
    sprint({ id: 2, name: "Closed", state: "done", can_manage: true }),
];

class ProjectSprint extends models.Model {
    _name = "project.sprint";
    name = fields.Char();
    _records = SPRINTS.map(({ id, name }) => ({ id, name }));
}

class TaskType extends models.Model {
    _name = "agile_community.task_type";
    name = fields.Char();
    _records = [
        { id: 1, name: "Task" },
        { id: 2, name: "Bug" },
    ];
}

class ProjectTask extends models.Model {
    _name = "project.task";
    name = fields.Char();
    issue_key = fields.Char();
    sequence = fields.Integer();
    story_points = fields.Float();
    story_points_estimated = fields.Boolean();
    user_ids = fields.Many2many({ relation: "res.users" });
    agile_task_type_id = fields.Many2one({ relation: "agile_community.task_type" });
    sprint_id = fields.Many2one({ relation: "project.sprint" });
    project_id = fields.Many2one({ relation: "project.project" });
    _records = [
        { id: 1, name: "One", issue_key: "WALK-1", sequence: 1, sprint_id: 1, story_points: 3, story_points_estimated: true, agile_task_type_id: 1 },
        { id: 2, name: "Two", issue_key: "WALK-2", sequence: 2, sprint_id: 1, agile_task_type_id: 1 },
        { id: 3, name: "Loose", issue_key: "WALK-3", sequence: 3, sprint_id: false, agile_task_type_id: 2 },
        { id: 4, name: "Done", issue_key: "WALK-4", sequence: 4, sprint_id: 2, story_points: 2, story_points_estimated: true, agile_task_type_id: 1 },
    ];
}

class ProjectProject extends models.Model {
    _name = "project.project";
    name = fields.Char();
    _records = [{ id: 7, name: "Walkthrough" }];
}

defineMailModels();
defineModels([ProjectSprint, TaskType, ProjectTask, ProjectProject]);

async function mountBacklog({ canEdit = true, sprints = SPRINTS } = {}) {
    onRpc("project.project", "agile_backlog_sprints", () => ({
        project_id: 7,
        can_edit: canEdit,
        task_types: [
            { id: 1, name: "Task" },
            { id: 2, name: "Bug" },
        ],
        members: [
            { id: 7, name: "Ada" },
            { id: 8, name: "Grace" },
        ],
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
                    <field name="story_points"/>
                    <field name="story_points_estimated" column_invisible="1"/>
                    <field name="user_ids" widget="many2many_tags"/>
                    <field name="agile_task_type_id"/>
                    <field name="sprint_id" column_invisible="1"/>
                </list>`,
    });
    await animationFrame();
    for (const header of document.querySelectorAll(".o_group_header:not(.o_group_open)")) {
        await contains(header).click();
    }
    await animationFrame();
}

// The mock server fills in defaults on what it receives; compare only the keys the app sent.
const pick = (values, keys) => Object.fromEntries(keys.map((key) => [key, values[key]]));
const SENT = ["name", "project_id", "agile_task_type_id", "sprint_id"];

const row = (key) => `.o_data_row:contains(${key})`;
const cell = (key, name) => `${row(key)} td[name=${name}]`;

function captureWrites() {
    const writes = [];
    onRpc("project.task", "write", ({ args }) => {
        writes.push({ ids: args[0], values: args[1] });
        return true;
    });
    return writes;
}

test("clicking the points cell opens an editor; Enter saves the estimate and the cell refreshes", async () => {
    const writes = captureWrites();
    await mountBacklog();
    await contains(cell("WALK-2", "story_points")).click();
    await waitFor(".o_ag_inline input");
    expect(".o_ag_inline_label").toHaveText("Points for WALK-2");
    expect(".o_ag_inline input").toHaveValue("");
    await fill("8");
    await press("Enter");
    await animationFrame();
    expect(writes).toEqual([{ ids: [2], values: { story_points_estimated: true, story_points: 8 } }]);
    expect(".o_ag_inline").toHaveCount(0);
    expect(".o_ag_live").toHaveText("WALK-2 estimate saved.");
});

test("an empty estimate means not estimated, and an editor for an estimated row starts with its points", async () => {
    const writes = captureWrites();
    await mountBacklog();
    await contains(cell("WALK-1", "story_points")).click();
    await waitFor(".o_ag_inline input");
    expect(".o_ag_inline input").toHaveValue("3");
    await fill("", { instantly: true });
    queryOne(".o_ag_inline input").value = "";
    queryOne(".o_ag_inline input").dispatchEvent(new Event("input", { bubbles: true }));
    await press("Enter");
    await animationFrame();
    expect(writes).toEqual([{ ids: [1], values: { story_points_estimated: false, story_points: 0 } }]);
});

test("invalid points show an error under the field, save nothing, and Esc cancels", async () => {
    const writes = captureWrites();
    await mountBacklog();
    await contains(cell("WALK-2", "story_points")).click();
    await waitFor(".o_ag_inline input");
    await fill("-2");
    await press("Enter");
    await animationFrame();
    expect(".o_ag_inline_error").toHaveText("Points must be a number of 0 or more.");
    expect(".o_ag_inline input").toHaveAttribute("aria-invalid", "true");
    expect(writes.length).toBe(0);
    await press("Escape");
    await animationFrame();
    expect(".o_ag_inline").toHaveCount(0);
    expect(writes.length).toBe(0);
});

test("a server refusal shows its reason under the field and keeps the editor open", async () => {
    onRpc("project.task", "write", () => {
        throw new Error("Only Agile team members can edit issues.");
    });
    await mountBacklog();
    await contains(cell("WALK-2", "story_points")).click();
    await waitFor(".o_ag_inline input");
    await fill("5");
    await press("Enter");
    await animationFrame();
    expect(".o_ag_inline_error").toHaveText("Only Agile team members can edit issues.");
    expect(".o_ag_inline").toHaveCount(1);
    expect(".o_ag_live").toHaveText("");
});

test("the assignee picker lists the team and saves the choice, including unassigned", async () => {
    const writes = captureWrites();
    await mountBacklog();
    await contains(cell("WALK-2", "user_ids")).click();
    await waitFor(".o_ag_inline select");
    expect(queryAllTexts(".o_ag_inline select option")).toEqual(["Unassigned", "Ada", "Grace"]);
    await contains(".o_ag_inline select").select("8");
    await animationFrame();
    expect(writes).toEqual([{ ids: [2], values: { user_ids: [[6, 0, [8]]] } }]);
    await contains(cell("WALK-2", "user_ids")).click();
    await waitFor(".o_ag_inline select");
    await contains(".o_ag_inline select").select("");
    await animationFrame();
    expect(writes.at(-1)).toEqual({ ids: [2], values: { user_ids: [[6, 0, []]] } });
});

test("the type picker offers the project's issue types", async () => {
    const writes = captureWrites();
    await mountBacklog();
    await contains(cell("WALK-2", "agile_task_type_id")).click();
    await waitFor(".o_ag_inline select");
    expect(queryAllTexts(".o_ag_inline select option")).toEqual(["Task", "Bug"]);
    await contains(".o_ag_inline select").select("2");
    await animationFrame();
    expect(writes).toEqual([{ ids: [2], values: { agile_task_type_id: 2 } }]);
});

test("e opens the editor from the keyboard", async () => {
    await mountBacklog();
    queryOne(cell("WALK-2", "story_points")).focus();
    await animationFrame();
    await press("e");
    await waitFor(".o_ag_inline input");
    expect(".o_ag_inline_label").toHaveText("Points for WALK-2");
});

test("users who cannot edit, and rows of completed sprints, get no editor", async () => {
    await mountBacklog({ canEdit: false });
    expect(".o_ag_can_edit").toHaveCount(0);
    expect(".o_ag_quick_row").toHaveCount(0);
});

test("completed sprint rows do not open an editor, from the keyboard or a click", async () => {
    mockService("action", {
        switchView() {},
        doAction() {},
    });
    await mountBacklog();
    expect(".o_ag_can_edit").toHaveCount(1);
    queryOne(cell("WALK-4", "story_points")).focus();
    await press("e");
    await animationFrame();
    expect(".o_ag_inline").toHaveCount(0);
    await contains(cell("WALK-4", "story_points")).click();
    await animationFrame();
    expect(".o_ag_inline").toHaveCount(0);
});

test("quick create adds an issue to the section, keeps the focus there and says what it made", async () => {
    const created = [];
    onRpc("project.task", "create", ({ args }) => {
        created.push(args[0][0]);
    });
    await mountBacklog();
    expect(".o_ag_quick_row").toHaveCount(2); // Planned and Backlog; none for the completed sprint
    await contains(".o_ag_quick_input[data-group-key='1']").click();
    await fill("Write the spec");
    await press("Enter");
    await animationFrame();
    await animationFrame();
    expect(created.map((values) => pick(values, SENT))).toEqual([
        { name: "Write the spec", project_id: 7, agile_task_type_id: 1, sprint_id: 1 },
    ]);
    // Unassigned says so, or Odoo assigns the creator (NU-11).
    expect(created[0].user_ids).toEqual([[6, 0, []]]);
    expect(".o_ag_quick_row .o_ag_inline_error").toHaveCount(0);
    expect(".o_notification_content").toHaveText(/created in Planned\./);
    expect(document.activeElement.dataset.groupKey).toBe("1");
    expect(".o_ag_quick_input[data-group-key='1']").toHaveValue("");
});

test("quick create sits on one line and can assign the new issue", async () => {
    const created = [];
    onRpc("project.task", "create", ({ args }) => {
        created.push(args[0][0]);
    });
    await mountBacklog();
    const line = ".o_ag_quick_row .o_ag_quick_line";
    expect(`${line} .o_ag_quick_type`).toHaveCount(2);
    expect(`${line} .o_ag_quick_input`).toHaveCount(2);
    expect(`${line} .o_ag_quick_assignee`).toHaveCount(2);
    await contains(".o_ag_quick_assignee:first").select("7");
    await contains(".o_ag_quick_input[data-group-key='1']").click();
    await fill("Assigned from the row");
    await press("Enter");
    await animationFrame();
    await animationFrame();
    expect(created[0].user_ids).toEqual([[6, 0, [7]]]);
});

test("quick create uses the chosen type, ignores an empty title and shows a refusal inline", async () => {
    const created = [];
    let refuse = false;
    onRpc("project.task", "create", ({ args }) => {
        if (refuse) {
            throw new Error("Only this project's Agile Manager can change sprint membership.");
        }
        created.push(args[0][0]);
    });
    await mountBacklog();
    await contains(".o_ag_quick_input[data-group-key='0']").click();
    await press("Enter");
    await animationFrame();
    expect(created.length).toBe(0);
    await contains(".o_ag_quick_row .o_ag_quick_type").select("2");
    await contains(".o_ag_quick_input[data-group-key='0']").click();
    await fill("Fix the crash");
    await press("Enter");
    await animationFrame();
    await animationFrame();
    expect(created.map((values) => pick(values, SENT))).toEqual([
        { name: "Fix the crash", project_id: 7, agile_task_type_id: 2, sprint_id: false },
    ]);
    refuse = true;
    await contains(".o_ag_quick_input[data-group-key='1']").click();
    await fill("Not allowed");
    await press("Enter");
    await animationFrame();
    expect(".o_ag_quick_row .o_ag_inline_error").toHaveText(
        "Only this project's Agile Manager can change sprint membership."
    );
    expect(".o_ag_quick_input[data-group-key='1']").toHaveValue("Not allowed");
});

test("sprints the user cannot manage get no quick-create row", async () => {
    await mountBacklog({
        sprints: [sprint({ id: 1, name: "Planned", can_manage: false }), SPRINTS[1]],
    });
    expect(".o_ag_quick_input[data-group-key='1']").toHaveCount(0);
    expect(".o_ag_quick_input[data-group-key='0']").toHaveCount(1);
});

test("the active sprint row has Complete sprint, for managers only", async () => {
    let opened;
    mockService("action", {
        switchView() {},
        doAction(action, options) {
            opened = { action, options };
        },
    });
    await mountBacklog({
        sprints: [sprint({ id: 1, name: "Active", state: "in_progress" }), SPRINTS[1]],
    });
    expect(".o_ag_complete_sprint").toHaveCount(1);
    await contains(".o_ag_complete_sprint").click();
    expect(opened.action).toBe("agile_scrum.action_project_sprint_close");
    expect(opened.options.additionalContext).toEqual({ active_id: 1 });
});

test("a sprint the user cannot manage shows no Complete sprint button", async () => {
    await mountBacklog({
        sprints: [sprint({ id: 1, name: "Active", state: "in_progress", can_manage: false }), SPRINTS[1]],
    });
    expect(".o_ag_complete_sprint").toHaveCount(0);
});

test("a completed sprint offers Reopen sprint to managers, off when it cannot be reopened", async () => {
    onRpc("project.sprint", "action_agile_open_reopen", ({ args }) => {
        return { type: "ir.actions.act_window", res_model: "agile.sprint.reopen", views: [[false, "form"]], target: "new", res_id: false, context: { default_sprint_id: args[0][0] } };
    });
    let opened;
    mockService("action", {
        switchView() {},
        doAction(action) {
            opened = action;
        },
    });
    await mountBacklog({
        sprints: [sprint({ id: 1, name: "Planned" }), sprint({ id: 2, name: "Closed", state: "done", can_manage: true, can_reopen: true })],
    });
    expect(".o_ag_reopen_sprint").toHaveCount(1);
    expect(".o_ag_reopen_sprint").not.toHaveAttribute("disabled");
    await contains(".o_ag_reopen_sprint").click();
    expect(opened.res_model).toBe("agile.sprint.reopen");
    expect(opened.context.default_sprint_id).toBe(2);
});

test("Reopen sprint is disabled when a later sprint started", async () => {
    await mountBacklog({
        sprints: [sprint({ id: 2, name: "Closed", state: "done", can_manage: true, can_reopen: false })],
    });
    expect(".o_ag_reopen_sprint").toHaveAttribute("disabled");
});

test("a completed sprint shows no Reopen sprint to people who cannot manage it", async () => {
    await mountBacklog({
        sprints: [sprint({ id: 3, name: "Closed", state: "done", can_manage: false, can_reopen: false })],
    });
    expect(".o_ag_reopen_sprint").toHaveCount(0);
});
