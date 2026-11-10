import { describe, expect, test } from "@odoo/hoot";
import { click, queryAll, queryAllTexts } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { epicProgress } from "@agile_community/backlog/backlog_helpers";
import {
    contains,
    defineModels,
    fields,
    makeTestApp,
    models,
    mountView,
    onRpc,
} from "@web/../tests/web_test_helpers";
import "@agile_community/backlog/agile_backlog_list";

describe.current.tags("desktop");

const txt = (value) => String(value);

class ProjectSprint extends models.Model {
    _name = "project.sprint";
    name = fields.Char();
    _records = [{ id: 1, name: "Planned" }];
}

class ProjectTask extends models.Model {
    _name = "project.task";
    name = fields.Char();
    issue_key = fields.Char();
    sequence = fields.Integer();
    sprint_id = fields.Many2one({ relation: "project.sprint" });
    parent_id = fields.Many2one({ relation: "project.task" });
    _records = [
        { id: 1, name: "One", issue_key: "WALK-1", sequence: 1, sprint_id: 1, parent_id: 10 },
        { id: 2, name: "Two", issue_key: "WALK-2", sequence: 2, sprint_id: 1, parent_id: 10 },
        { id: 3, name: "Three", issue_key: "WALK-3", sequence: 3, sprint_id: 1, parent_id: 11 },
        { id: 4, name: "Four", issue_key: "WALK-4", sequence: 4, sprint_id: 1, parent_id: false },
        // The epics themselves: no sprint, so the list shows them under "None", which these tests ignore.
        { id: 10, name: "Planning UX", issue_key: "WALK-10", sequence: 10, sprint_id: false, parent_id: false },
        { id: 11, name: "Reports", issue_key: "WALK-11", sequence: 11, sprint_id: false, parent_id: false },
    ];
}

class ProjectProject extends models.Model {
    _name = "project.project";
    name = fields.Char();
}

defineMailModels();
defineModels([ProjectSprint, ProjectTask, ProjectProject]);

const EPICS = [
    { id: 10, name: "Planning UX", issue_key: "WALK-10", children: 8, done_children: 3, points: 24, done_points: 11 },
    { id: 11, name: "Reports", issue_key: "WALK-11", children: 2, done_children: 0, points: 0, done_points: 0 },
    { id: 12, name: "Nothing yet", issue_key: "WALK-12", children: 0, done_children: 0, points: 0, done_points: 0 },
];

async function mountBacklog({ epics = EPICS, failEpics = false } = {}) {
    onRpc("project.project", "agile_backlog_sprints", () => ({
        project_id: 7,
        can_edit: false,
        task_types: [],
        members: [],
        sprints: [
            {
                id: 1, name: "Planned", state: "draft", date_start: "2026-11-02", date_end: "2026-11-15",
                goal: "", planned_points: 0, capacity_points: 0, over_capacity: false,
                planning_confirmed: false, planning_stale: false, unestimated_count: 0,
                points_by_status: {}, completed_points: 0, committed_points_at_close: 0, can_manage: false,
            },
        ],
        backlog: { issue_count: 0, unestimated_count: 0 },
    }));
    onRpc("project.project", "agile_backlog_epics", () => {
        if (failEpics) {
            throw new Error("not a member");
        }
        return { project_id: 7, epics };
    });
    // Like the server, keep the sprint in the result when a filter leaves it without issues.
    onRpc("project.task", "web_read_group", async ({ parent }) => {
        const result = await parent();
        if (!result.groups.some((group) => group.sprint_id?.[0] === 1)) {
            result.groups.unshift({
                sprint_id: [1, "Planned"],
                __extra_domain: [["sprint_id", "=", 1]],
                __count: 0,
            });
        }
        return result;
    });
    await mountView({
        type: "list",
        resModel: "project.task",
        context: { default_project_id: 7 },
        groupBy: ["sprint_id"],
        arch: `<list js_class="agile_backlog_list" expand="1" default_order="sequence, id">
                    <field name="sequence" widget="handle"/>
                    <field name="issue_key"/>
                    <field name="name"/>
                    <field name="parent_id" column_invisible="1"/>
                    <field name="sprint_id" column_invisible="1"/>
                </list>`,
    });
    await animationFrame();
}

// Only the four work issues; the two epic rows sit in the Backlog group.
const keys = () =>
    queryAllTexts(".o_data_row td[name=issue_key]").filter((key) => !["WALK-10", "WALK-11"].includes(key));

test("an epic counted by issues does not repeat itself on a second line", async () => {
    await makeTestApp();
    expect(epicProgress(EPICS[0], "issues").points).toBe("");
    expect(txt(epicProgress(EPICS[0], "hours").points)).toBe("11 of 24 hours");
});

test("progress words and bar follow points when an epic has them, issues when it does not", async () => {
    await makeTestApp();
    const withPoints = epicProgress(EPICS[0]);
    expect(withPoints.percent).toBe(46); // 11 of 24 points
    expect(txt(withPoints.issues)).toBe("3 of 8 issues done");
    expect(txt(withPoints.points)).toBe("11 of 24 points");
    const issuesOnly = epicProgress({ ...EPICS[1], children: 4, done_children: 1 });
    expect(issuesOnly.percent).toBe(25);
    expect(issuesOnly.points).toBe("");
    const empty = epicProgress(EPICS[2]);
    expect(empty.percent).toBe(0);
    expect(txt(empty.issues)).toBe("No issues yet");
    expect(epicProgress({ ...EPICS[0], done_points: 99 }).percent).toBe(100);
});

test("the panel lists every epic with its progress in words and as a labelled bar", async () => {
    await mountBacklog();
    expect(".o_ag_epics_toggle").toHaveText("Epics (3)");
    expect(".o_ag_epic").toHaveCount(3);
    expect(queryAllTexts(".o_ag_epic_name").map((text) => text.replace(/\s+/g, " "))).toEqual([
        "WALK-10 Planning UX",
        "WALK-11 Reports",
        "WALK-12 Nothing yet",
    ]);
    expect(queryAllTexts(".o_ag_epic_text")).toEqual([
        "3 of 8 issues done, 11 of 24 points",
        "0 of 2 issues done",
        "No issues yet",
    ]);
    expect(queryAll(".o_ag_epic .o_ag_epic_bar")[0].getAttribute("aria-label")).toBe(
        "3 of 8 issues done, 11 of 24 points"
    );
    expect(queryAll(".o_ag_epic .o_ag_epic_bar i")[0].style.width).toBe("46%");
    expect(".o_ag_epic[aria-pressed='true']").toHaveCount(0);
});

test("choosing an epic filters the backlog, choosing it again clears it, choosing another replaces it", async () => {
    await mountBacklog();
    expect(keys()).toEqual(["WALK-1", "WALK-2", "WALK-3", "WALK-4"]);
    await contains(".o_ag_epic[data-epic-id='10']").click();
    await animationFrame();
    expect(keys()).toEqual(["WALK-1", "WALK-2"]);
    expect(".o_ag_epic[data-epic-id='10']").toHaveAttribute("aria-pressed", "true");
    await contains(".o_ag_epic[data-epic-id='11']").click();
    await animationFrame();
    expect(keys()).toEqual(["WALK-3"]);
    expect(".o_ag_epic[aria-pressed='true']").toHaveCount(1);
    expect(".o_ag_epic[data-epic-id='11']").toHaveAttribute("aria-pressed", "true");
    await contains(".o_ag_epic[data-epic-id='11']").click();
    await animationFrame();
    expect(keys()).toEqual(["WALK-1", "WALK-2", "WALK-3", "WALK-4"]);
    expect(".o_ag_epic[aria-pressed='true']").toHaveCount(0);
});

test("a sprint that an epic filter emptied opens again when the next epic has rows for it", async () => {
    await mountBacklog();
    await contains(".o_ag_epic[data-epic-id='12']").click();
    await animationFrame();
    expect(keys()).toEqual([]);
    await contains(".o_ag_epic[data-epic-id='10']").click();
    await animationFrame();
    await animationFrame();
    expect(keys()).toEqual(["WALK-1", "WALK-2"]);
});

test("a sprint the person folded stays folded while the epic filter changes", async () => {
    await mountBacklog();
    await contains(".o_group_header:contains('Planned')").click();
    await animationFrame();
    expect(keys()).toEqual([]);
    await contains(".o_ag_epic[data-epic-id='12']").click();
    await animationFrame();
    await contains(".o_ag_epic[data-epic-id='10']").click();
    await animationFrame();
    await animationFrame();
    expect(keys()).toEqual([]);
});

test("the panel can be collapsed and says so when there are no epics", async () => {
    await mountBacklog();
    await click(".o_ag_epics_toggle");
    await animationFrame();
    expect(".o_ag_epic").toHaveCount(0);
    expect(".o_ag_epics_toggle").toHaveAttribute("aria-expanded", "false");
    await click(".o_ag_epics_toggle");
    await animationFrame();
    expect(".o_ag_epic").toHaveCount(3);
});

test("a project without epics shows an invitation, and a failed request hides the panel only", async () => {
    await mountBacklog({ epics: [] });
    expect(".o_ag_epics_empty").toHaveCount(1);
    expect(".o_ag_epics_empty").toHaveText(/No epics yet/);
    expect(keys().length).toBe(4);
});

test("when the epic request fails the rows and headers still work", async () => {
    await mountBacklog({ failEpics: true });
    expect(".o_ag_epics").toHaveCount(0);
    expect(keys().length).toBe(4);
    expect(".o_ag_group_name").toHaveCount(2); // Planned and Backlog
});
