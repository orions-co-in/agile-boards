import { describe, expect, test } from "@odoo/hoot";
import { sidebarTarget } from "@agile_community/sidebar/sidebar_helpers";

describe.current.tags("desktop");

const win = (res_model, context, extra = {}) => ({
    action: { type: "ir.actions.act_window", res_model, context, ...extra },
    props: {},
});

test("a client action names its project and entry", () => {
    const controller = { action: { type: "ir.actions.client", tag: "agile_community.reports", params: { project_id: 7 } } };
    expect(sidebarTarget(controller)).toEqual({ projectId: 7, entry: "reports" });
});

test("a client action restored from its URL falls back to active_id", () => {
    const controller = { action: { type: "ir.actions.client", tag: "agile_community.overview", context: { active_id: 3 } } };
    expect(sidebarTarget(controller)).toEqual({ projectId: 3, entry: "summary" });
});

test("the permissions page belongs to Settings, also when restored from its URL", () => {
    const named = { action: { type: "ir.actions.client", tag: "agile_community.permissions", params: { project_id: 5 } } };
    expect(sidebarTarget(named)).toEqual({ projectId: 5, entry: "settings" });
    const restored = { action: { type: "ir.actions.client", tag: "agile_community.permissions", context: { active_id: 5 } } };
    expect(sidebarTarget(restored)).toEqual({ projectId: 5, entry: "settings" });
});

test("the roadmap of several projects has no sidebar", () => {
    const controller = { action: { type: "ir.actions.client", tag: "agile_community.roadmap", params: { project_ids: [1, 2] } } };
    expect(sidebarTarget(controller)).toBe(null);
});

test("tasks open as the board, or as the backlog when flagged", () => {
    expect(sidebarTarget(win("project.task", { default_project_id: 4, agile_project_view: true }))).toEqual({ projectId: 4, entry: "board" });
    expect(
        sidebarTarget(win("project.task", { default_project_id: 4, agile_project_view: true, agile_backlog: true }))
    ).toEqual({ projectId: 4, entry: "backlog" });
});

test("sprints, releases and components map to their entries", () => {
    expect(sidebarTarget(win("project.sprint", { default_project_id: 2 })).entry).toBe("sprints");
    expect(sidebarTarget(win("project.version", { default_project_id: 2 })).entry).toBe("releases");
    expect(sidebarTarget(win("agile.project.component", { default_project_id: 2 })).entry).toBe("components");
});

test("screens opened from the project settings keep the sidebar on Settings", () => {
    for (const model of ["agile.workflow", "agile.automation.rule", "agile.custom.field", "agile.board", "agile.filter"]) {
        expect(sidebarTarget(win(model, { default_project_id: 2 })).entry).toBe("settings");
    }
    expect(sidebarTarget(win("agile.workflow", {}))).toBe(null);
});

test("settings opens the project form; other screens and dialogs get no sidebar", () => {
    expect(
        sidebarTarget({ action: { type: "ir.actions.act_window", res_model: "project.project", context: { agile_sidebar_settings: true } }, props: { resId: 9 } })
    ).toEqual({ projectId: 9, entry: "settings" });
    expect(sidebarTarget(win("project.task", {}))).toBe(null);
    expect(sidebarTarget(win("project.task", { default_project_id: 4, agile_project_view: true }, { target: "new" }))).toBe(null);
    expect(sidebarTarget(null)).toBe(null);
});
