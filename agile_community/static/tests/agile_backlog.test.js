import { describe, expect, test } from "@odoo/hoot";
import { queryAllTexts } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { defineModels, fields, makeMockEnv, models, mountView, onRpc } from "@web/../tests/web_test_helpers";
import {
    backlogText,
    dateRange,
    planChip,
    pointsText,
    ribbonLabel,
    ribbonSegments,
    stateLabel,
    unestimatedText,
} from "@agile_community/backlog/backlog_helpers";
import "@agile_community/backlog/agile_backlog_list";

describe.current.tags("desktop");

const sprint = (extra = {}) => ({
    id: 1,
    name: "Sprint 14",
    state: "draft",
    date_start: "2026-10-20",
    date_end: "2026-11-03",
    goal: "Usable backlog",
    planned_points: 14,
    capacity_points: 14,
    over_capacity: false,
    planning_confirmed: true,
    planning_stale: false,
    unestimated_count: 0,
    points_by_status: { done: 5, progress: 4, backlog: 5 },
    completed_points: 0,
    committed_points_at_close: 0,
    can_manage: true,
    ...extra,
});

const txt = (value) => String(value);

test("points text states the total, capacity and over capacity in words", async () => {
    await makeMockEnv();
    expect(txt(pointsText(sprint()))).toBe("14 of 14 points");
    expect(txt(pointsText(sprint({ capacity_points: 0 })))).toBe("14 points planned");
    expect(txt(pointsText(sprint({ planned_points: 18, over_capacity: true })))).toBe(
        "Over capacity by 4 points: 18 of 14"
    );
    const done = { state: "done", completed_points: 26, committed_points_at_close: 30 };
    expect(txt(pointsText(sprint(done)))).toBe("26 of 30 points done, 4 carried over");
    expect(txt(pointsText(sprint({ ...done, completed_points: 30 })))).toBe("30 of 30 points done");
});

test("the sprint total reads in the project's estimate unit", async () => {
    await makeMockEnv();
    expect(txt(pointsText(sprint(), "hours"))).toBe("14 of 14 hours");
    expect(txt(pointsText(sprint({ capacity_points: 0 }), "issues"))).toBe("14 issues planned");
    expect(txt(pointsText(sprint(), "points"))).toBe("14 of 14 points");
});

test("plan chip follows not confirmed, confirmed, then changed since confirmed", async () => {
    await makeMockEnv();
    expect(txt(planChip(sprint({ planning_confirmed: false })).text)).toBe("Plan not confirmed");
    expect(planChip(sprint({ planning_confirmed: false })).action).toBe("action_confirm_plan");
    expect(txt(planChip(sprint()).text)).toBe("Plan confirmed");
    expect(planChip(sprint()).action).toBe("action_agile_open_start");
    const stale = planChip(sprint({ planning_stale: true }));
    expect(txt(stale.text)).toBe("Plan changed since it was confirmed");
    expect(stale.action).toBe("action_open_scope_change");
    expect(stale.startBlocked).toBe(true);
    expect(stale.tone).toBe("danger");
    expect(planChip(sprint({ state: "in_progress" }))).toBe(null);
    expect(planChip(sprint({ state: "done" }))).toBe(null);
});

test("ribbon segments are ordered by status, scaled to capacity and capped", async () => {
    await makeMockEnv();
    const segments = ribbonSegments(sprint());
    expect(segments.map((s) => s.status)).toEqual(["done", "progress", "backlog"]);
    expect(Math.abs(segments[0].width - (5 / 14) * 100) < 1e-6).toBe(true);
    const over = ribbonSegments(sprint({ planned_points: 30, capacity_points: 10, points_by_status: { done: 30 } }));
    expect(over[0].width).toBe(100);
    expect(ribbonSegments(sprint({ points_by_status: {} }))).toEqual([]);
    expect(ribbonLabel(sprint())).toInclude("14 of 14 points");
    expect(ribbonLabel(sprint())).toInclude("done: 5");
});

test("labels, unestimated count and backlog totals read plainly", async () => {
    await makeMockEnv();
    expect(txt(stateLabel(sprint({ state: "in_progress" })))).toBe("Active");
    expect(txt(stateLabel(sprint({ state: "done" })))).toBe("Completed");
    expect(dateRange(sprint())).toMatch(/Oct.*–.*Nov/);
    expect(txt(unestimatedText(0))).toBe("");
    expect(txt(unestimatedText(3))).toBe("3 not estimated");
    expect(txt(backlogText({ issue_count: 2003, unestimated_count: 1 }))).toBe(
        "2003 issues, 1 not estimated"
    );
    expect(txt(backlogText({ issue_count: 4, unestimated_count: 0 }))).toBe("4 issues");
    expect(backlogText(null)).toBe("");
});

class ProjectSprint extends models.Model {
    _name = "project.sprint";
    name = fields.Char();
    _records = [{ id: 1, name: "Sprint 14" }];
}

class ProjectTask extends models.Model {
    _name = "project.task";
    name = fields.Char();
    sequence = fields.Integer();
    sprint_id = fields.Many2one({ relation: "project.sprint" });
    _records = [
        { id: 1, name: "First", sequence: 1, sprint_id: 1 },
        { id: 2, name: "Second", sequence: 2, sprint_id: 1 },
        { id: 3, name: "Loose", sequence: 3, sprint_id: false },
    ];
}

class ProjectProject extends models.Model {
    _name = "project.project";
    name = fields.Char();
}

defineMailModels();
defineModels([ProjectSprint, ProjectTask, ProjectProject]);

test("grouped list shows sprint headers with plan state, an unestimated count and the backlog total", async () => {
    onRpc("project.project", "agile_backlog_sprints", () => ({
        project_id: 7,
        sprints: [sprint({ planning_stale: true, unestimated_count: 2 })],
        backlog: { issue_count: 1, unestimated_count: 1 },
    }));
    await mountView({
        type: "list",
        resModel: "project.task",
        context: { default_project_id: 7 },
        groupBy: ["sprint_id"],
        arch: `<list js_class="agile_backlog_list" expand="1">
                    <field name="sequence" widget="handle"/>
                    <field name="name"/>
                    <field name="sprint_id" column_invisible="1"/>
                </list>`,
    });
    await animationFrame();
    expect(queryAllTexts(".o_ag_group_name")).toEqual(["Sprint 14", "Backlog"]);
    expect(".o_ag_sprint_draft").toHaveText("Planned");
    expect(".o_ag_plan_chip").toHaveText("Plan changed since it was confirmed");
    expect(".o_ag_plan_action").toHaveText("Update plan");
    expect(".o_ag_group button[disabled]").toHaveText("Start sprint");
    expect(".o_ag_group_points").toHaveText("14 of 14 points");
    expect(".o_ag_ribbon").toHaveAttribute("role", "img");
    expect(queryAllTexts(".o_ag_group_meta")).toInclude("2 not estimated");
    expect(queryAllTexts(".o_ag_group_meta")).toInclude("1 issues, 1 not estimated");
    expect(".o_data_row").toHaveCount(3); // the Backlog group opens on load (NU-29)
});

test("header actions are hidden from users who cannot manage the sprint", async () => {
    onRpc("project.project", "agile_backlog_sprints", () => ({
        project_id: 7,
        sprints: [sprint({ planning_confirmed: false, can_manage: false })],
        backlog: { issue_count: 1, unestimated_count: 0 },
    }));
    await mountView({
        type: "list",
        resModel: "project.task",
        context: { default_project_id: 7 },
        groupBy: ["sprint_id"],
        arch: `<list js_class="agile_backlog_list" expand="1">
                    <field name="name"/>
                    <field name="sprint_id" column_invisible="1"/>
                </list>`,
    });
    await animationFrame();
    expect(".o_ag_plan_chip").toHaveText("Plan not confirmed");
    expect(".o_ag_plan_action").toHaveCount(0);
});

test("a failed header request keeps the rows and offers a retry", async () => {
    let calls = 0;
    onRpc("project.project", "agile_backlog_sprints", () => {
        calls++;
        if (calls === 1) {
            throw new Error("boom");
        }
        return { project_id: 7, sprints: [sprint()], backlog: { issue_count: 1, unestimated_count: 0 } };
    });
    await mountView({
        type: "list",
        resModel: "project.task",
        context: { default_project_id: 7 },
        groupBy: ["sprint_id"],
        arch: `<list js_class="agile_backlog_list" expand="1">
                    <field name="name"/>
                    <field name="sprint_id" column_invisible="1"/>
                </list>`,
    });
    await animationFrame();
    expect(".o_data_row").toHaveCount(3);
    expect(queryAllTexts(".o_ag_group_meta")).toInclude("Sprint details unavailable");
});
