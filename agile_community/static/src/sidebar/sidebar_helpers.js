import { _t } from "@web/core/l10n/translation";

// Sidebar entries in display order, grouped as in the D-801 design.
export const SIDEBAR_ENTRIES = [
    { key: "summary", label: _t("Summary"), group: _t("Plan"), icon: "M3 3h7v9H3zM14 3h7v5h-7zM14 12h7v9h-7zM3 16h7v5H3z" },
    { key: "roadmap", label: _t("Roadmap"), group: _t("Plan"), icon: "M3 6h10M3 12h16M3 18h8" },
    { key: "capacity", label: _t("Capacity"), group: _t("Plan"), icon: "M4 20V12M10 20V6M16 20v-5M22 20H2M4 8l6-4 6 5 6-4" },
    { key: "backlog", label: _t("Backlog"), group: _t("Plan"), icon: "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" },
    { key: "board", label: _t("Board"), group: _t("Work"), icon: "M3 4h5v16H3zM10 4h5v10h-5zM17 4h4v13h-4z" },
    { key: "sprints", label: _t("Sprints"), group: _t("Work"), icon: "M21 12a9 9 0 1 1-3-6.7M21 4v5h-5" },
    { key: "mine", label: _t("Your work"), group: _t("Work"), icon: "M12 4a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM4 21c1-4 4-6 8-6s7 2 8 6" },
    { key: "reports", label: _t("Reports"), group: _t("Insight"), icon: "M4 20V10M10 20V4M16 20v-8M22 20H2" },
    { key: "releases", label: _t("Releases"), group: _t("Insight"), icon: "M5 21V4M5 4h12l-2 4 2 4H5" },
    { key: "components", label: _t("Components"), group: _t("Project"), icon: "M3 3h8v8H3zM13 13h8v8h-8zM13 7h8M3 17h8" },
    { key: "settings", label: _t("Settings"), group: _t("Project"), icon: "M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM12 2v3M12 19v3M2 12h3M19 12h3" },
];

// The five entries kept on the phone bottom bar; the rest sit in "More".
export const BOTTOM_KEYS = ["summary", "backlog", "board", "reports"];

const CLIENT_ENTRY = {
    "agile_community.summary": "summary",
    "agile_community.overview": "summary",
    "agile_community.reports": "reports",
    "agile_community.roadmap": "roadmap",
    "agile_community.capacity": "capacity",
    "agile_community.your_work": "mine",
    "agile_community.permissions": "settings",
};

const MODEL_ENTRY = {
    "project.sprint": "sprints",
    "project.version": "releases",
    "agile.project.component": "components",
    // Screens opened from the project settings stay inside the Agile shell (NU-14).
    "agile.workflow": "settings",
    "agile.automation.rule": "settings",
    "agile.automation.run": "settings",
    "agile.custom.field": "settings",
    "agile.board": "settings",
    "agile.filter": "settings",
    "agile.security.level": "settings",
    "agile.project.quick.filter": "settings",
    "agile.project.view.preference": "settings",
    "agile.hook.delivery": "settings",
    "agile.audit": "settings",
    "agile.project.member": "settings",
};

/**
 * Which project and which sidebar entry a controller belongs to.
 * Returns null for screens that are not an Agile project screen (no sidebar).
 */
export function sidebarTarget(controller) {
    const action = controller?.action;
    if (!action || action.target === "new") {
        return null;
    }
    const context = action.context || {};
    // A screen can name its own entry (the delivery reports are other models).
    if (context.agile_sidebar_entry && context.default_project_id) {
        return { projectId: context.default_project_id, entry: context.agile_sidebar_entry };
    }
    if (action.type === "ir.actions.client") {
        const params = action.params || {};
        // A screen restored from its URL has no params, only the project as active_id.
        const projectId =
            params.project_id ??
            (params.project_ids?.length === 1 ? params.project_ids[0] : null) ??
            context.active_id ??
            context.default_project_id;
        const entry = CLIENT_ENTRY[action.tag];
        return projectId && entry ? { projectId, entry } : null;
    }
    if (action.type !== "ir.actions.act_window") {
        return null;
    }
    if (action.res_model === "project.project" && context.agile_sidebar_settings) {
        const projectId = controller.props?.resId || action.res_id;
        return projectId ? { projectId, entry: "settings" } : null;
    }
    const projectId = context.default_project_id;
    if (!projectId) {
        return null;
    }
    if (action.res_model === "project.task" && context.agile_project_view) {
        return { projectId, entry: context.agile_backlog ? "backlog" : "board" };
    }
    const entry = MODEL_ENTRY[action.res_model];
    return entry ? { projectId, entry } : null;
}
