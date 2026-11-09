import { describe, expect, test } from "@odoo/hoot";
import { sidebarTarget } from "@agile_community/sidebar/sidebar_helpers";
import { YOUR_WORK_TABS } from "@agile_community/your_work/agile_your_work";

describe.current.tags("desktop");

test("Your work has the four tabs of My Work", () => {
    expect(YOUR_WORK_TABS.map((tab) => tab.key)).toEqual(["assigned", "review", "blocked", "due"]);
});

test("the Your work screen highlights its sidebar entry", () => {
    const controller = { action: { type: "ir.actions.client", tag: "agile_community.your_work", params: { project_id: 5 } } };
    expect(sidebarTarget(controller)).toEqual({ projectId: 5, entry: "mine" });
});

test("a delivery report names its own sidebar entry", () => {
    const controller = {
        action: {
            type: "ir.actions.act_window",
            res_model: "project.sprint",
            context: { default_project_id: 8, agile_sidebar_entry: "reports" },
        },
    };
    expect(sidebarTarget(controller)).toEqual({ projectId: 8, entry: "reports" });
});
