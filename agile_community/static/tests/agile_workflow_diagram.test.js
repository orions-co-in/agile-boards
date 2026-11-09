import { describe, expect, test } from "@odoo/hoot";
import { queryAll, queryAllTexts } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { defineModels, fields, makeMockEnv, models, mountView } from "@web/../tests/web_test_helpers";
import { flowLayout, rolesText } from "@agile_community/workflow/agile_workflow_diagram";

describe.current.tags("desktop");

const DIAGRAM = {
    statuses: [
        { stage_id: 1, name: "Backlog", category: "backlog", count: 2 },
        { stage_id: 2, name: "Ready", category: "ready", count: 1 },
        { stage_id: 3, name: "Canceled", category: "canceled", count: 0 },
    ],
    moves: [
        { name: "Mark ready", from: 1, to: 2, roles: ["Contributors", "Managers"] },
        { name: "Cancel", from: 2, to: 3, roles: ["Managers"] },
        { name: "Reopen", from: 3, to: 1, roles: ["Managers"] },
        { name: "Ghost", from: 1, to: 99, roles: ["Managers"] },
    ],
};

class AgileWorkflow extends models.Model {
    _name = "agile.workflow";
    name = fields.Char();
    diagram = fields.Json();
    _records = [{ id: 1, name: "Default workflow", diagram: DIAGRAM }];
}

defineMailModels();
defineModels([AgileWorkflow]);

test("statuses sit left to right, forward moves arc above and backward moves below", async () => {
    await makeMockEnv();
    const flow = flowLayout(DIAGRAM);
    expect(flow.boxes.map((box) => box.name)).toEqual(["Backlog", "Ready", "Canceled"]);
    expect(flow.boxes[0].x < flow.boxes[1].x && flow.boxes[1].x < flow.boxes[2].x).toBe(true);
    // A move to a status that is not in the workflow is not drawn.
    expect(flow.arrows.map((arrow) => arrow.name)).toEqual(["Mark ready", "Cancel", "Reopen"]);
    const [markReady, cancel, reopen] = flow.arrows;
    expect(markReady.forward).toBe(true);
    expect(reopen.forward).toBe(false);
    expect(reopen.ly > flow.boxes[0].y + flow.boxes[0].h).toBe(true); // below the boxes
    expect(markReady.ly < flow.boxes[0].y).toBe(true); // above the boxes
    // Managers-only moves are dashed and say so; shared moves are plain.
    expect(cancel.dashed).toBe(true);
    expect(cancel.label).toBe("Cancel (managers)");
    expect(markReady.dashed).toBe(false);
    expect(markReady.aria).toBe("Move Mark ready: Backlog to Ready, contributors, managers");
});

test("an empty workflow lays out without boxes and roles read in words", async () => {
    await makeMockEnv();
    expect(flowLayout(null).boxes).toEqual([]);
    expect(rolesText([])).toBe("nobody");
    expect(rolesText(["Contributors", "Managers"])).toBe("contributors, managers");
});

test("the picture shows each status with its issue count and each move as a named button", async () => {
    await mountView({
        type: "form",
        resModel: "agile.workflow",
        resId: 1,
        arch: `<form><field name="diagram" widget="agile_workflow_diagram" nolabel="1"/></form>`,
    });
    await animationFrame();
    expect(".o_ag_flow_box").toHaveCount(3);
    expect(".o_ag_flow_move").toHaveCount(3);
    expect(queryAllTexts(".o_ag_flow_box .o_ag_flow_count")).toEqual(["2 issues", "1 issue", "no issues"]);
    expect(queryAll(".o_ag_flow_box")[0].getAttribute("aria-label")).toBe("Status Backlog, 2 issues");
    expect(".o_ag_flow_svg").toHaveAttribute("aria-label", /The lists below hold the same information/);
});

test("a box with no statuses invites adding one", async () => {
    AgileWorkflow._records = [{ id: 1, name: "Empty", diagram: { statuses: [], moves: [] } }];
    await mountView({
        type: "form",
        resModel: "agile.workflow",
        resId: 1,
        arch: `<form><field name="diagram" widget="agile_workflow_diagram" nolabel="1"/></form>`,
    });
    await animationFrame();
    expect(".o_ag_flow").toHaveText("Add a status to see the flow.");
});

test("brackets say the backlog is outside the sprint and To Do to Done is the sprint", () => {
    const statuses = [
        { stage_id: 1, name: "Backlog", category: "backlog", count: 2 },
        { stage_id: 2, name: "To Do", category: "ready", count: 1 },
        { stage_id: 3, name: "In Progress", category: "progress", count: 0 },
        { stage_id: 4, name: "Canceled", category: "canceled", count: 0 },
    ];
    const flow = flowLayout({ statuses, moves: [] });
    expect(flow.brackets.map((bracket) => bracket.key)).toEqual(["backlog", "sprint", "closed"]);
    const sprint = flow.brackets[1];
    expect(sprint.x1).toBe(flow.brackets[0].x2 + 64);
    expect(sprint.x2 > sprint.x1).toBe(true);
});

test("moves with one name into one status share a single label", async () => {
    await makeMockEnv();
    const diagram = {
        statuses: [1, 2, 3, 4].map((id) => ({ stage_id: id, name: `S${id}`, category: "ready", count: 0 })),
        moves: [1, 2, 3].map((from) => ({ id: from, name: "Cancel Issue", from, to: 4, roles: [], conditions: [], actions: [] })),
    };
    const { arrows } = flowLayout(diagram);
    expect(arrows.filter((arrow) => arrow.showLabel).length).toBe(1);
    expect(arrows.find((arrow) => arrow.showLabel).shownLabel).toMatch(/from 3 statuses/);
});
