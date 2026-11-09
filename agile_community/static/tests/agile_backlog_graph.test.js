import { describe, expect, test } from "@odoo/hoot";
import { click, queryAllTexts } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { defineModels, fields, models, mountView } from "@web/../tests/web_test_helpers";
import "@agile_community/backlog_graph/agile_backlog_graph";

describe.current.tags("desktop");

class ProjectTaskType extends models.Model {
    _name = "project.task.type";
    name = fields.Char();
    _records = [
        { id: 1, name: "Backlog" },
        { id: 2, name: "Done" },
    ];
}

class ProjectTask extends models.Model {
    _name = "project.task";
    name = fields.Char();
    stage_id = fields.Many2one({ relation: "project.task.type" });
    story_points = fields.Float({ string: "Story points" });
    _records = [
        { id: 1, name: "A", stage_id: 1, story_points: 5 },
        { id: 2, name: "B", stage_id: 1, story_points: 8.5 },
        { id: 3, name: "C", stage_id: 2, story_points: 3 },
    ];
}

defineMailModels();
defineModels([ProjectTaskType, ProjectTask]);

const ARCH = `<graph js_class="agile_backlog_graph" type="bar">
    <field name="stage_id"/>
    <field name="story_points" type="measure"/>
</graph>`;

test("the graph offers its figures as a table behind 'Show the numbers'", async () => {
    await mountView({ type: "graph", resModel: "project.task", arch: ARCH });
    await animationFrame();
    expect(".o_ag_graph_numbers summary").toHaveText("Show the numbers");
    expect(".o_ag_graph_numbers").not.toHaveAttribute("open");
    await click(".o_ag_graph_numbers summary");
    await animationFrame();
    expect(queryAllTexts(".o_ag_graph_numbers thead th")).toEqual(["Group", "Story points", "Issues"]);
    expect(queryAllTexts(".o_ag_graph_numbers tbody tr").map((row) => row.replace(/\s+/g, " "))).toEqual([
        "Backlog 13.50 2",
        "Done 3.00 1",
    ]);
    expect(".o_ag_graph_numbers caption").toHaveCount(1);
});

test("no data, no numbers table", async () => {
    ProjectTask._records = [];
    await mountView({ type: "graph", resModel: "project.task", arch: ARCH });
    await animationFrame();
    expect(".o_ag_graph_numbers").toHaveCount(0);
});
