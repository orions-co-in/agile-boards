import { _t } from "@web/core/l10n/translation";
import { deserializeDate } from "@web/core/l10n/dates";
import { unitWord } from "../estimate_unit";

export const STATUS_ORDER = ["done", "review", "progress", "ready", "backlog"];
const SHORT_DATE = { day: "numeric", month: "short" };

export function formatPoints(value) {
    return String(Math.round((value || 0) * 100) / 100);
}

function shortDate(isoDate) {
    return deserializeDate(isoDate).toLocaleString(SHORT_DATE);
}

export function stateLabel(sprint) {
    return { draft: _t("Planned"), in_progress: _t("Active"), done: _t("Completed") }[sprint.state];
}

export function dateRange(sprint) {
    return `${shortDate(sprint.date_start)} – ${shortDate(sprint.date_end)}`;
}

/** Words for the points total; over capacity is never conveyed by colour alone. */
export function pointsText(sprint, unit) {
    const word = unitWord(unit);
    const planned = formatPoints(sprint.planned_points);
    if (sprint.state === "done") {
        const done = formatPoints(sprint.completed_points);
        const committed = formatPoints(sprint.committed_points_at_close);
        const carried = Math.max(sprint.committed_points_at_close - sprint.completed_points, 0);
        return carried
            ? _t("%(done)s of %(committed)s %(unit)s done, %(carried)s carried over", {
                  unit: word,
                  done,
                  committed,
                  carried: formatPoints(carried),
              })
            : _t("%(done)s of %(committed)s %(unit)s done", { done, committed, unit: word });
    }
    if (!sprint.capacity_points) {
        return _t("%(planned)s %(unit)s planned", { planned, unit: word });
    }
    if (sprint.over_capacity) {
        return _t("Over capacity by %(over)s %(unit)s: %(planned)s of %(capacity)s", {
        unit: word,
            over: formatPoints(sprint.planned_points - sprint.capacity_points),
            planned,
            capacity: formatPoints(sprint.capacity_points),
        });
    }
    return _t("%(planned)s of %(capacity)s %(unit)s", {
        unit: word,
        planned,
        capacity: formatPoints(sprint.capacity_points),
    });
}

export function ribbonSegments(sprint) {
    const scale = Math.max(sprint.capacity_points || 0, sprint.planned_points || 0, 1);
    return STATUS_ORDER.filter((status) => sprint.points_by_status[status]).map((status) => ({
        status,
        width: Math.min((sprint.points_by_status[status] / scale) * 100, 100),
        label: `${status}: ${formatPoints(sprint.points_by_status[status])}`,
    }));
}

export function ribbonLabel(sprint, unit) {
    const parts = ribbonSegments(sprint).map((segment) => segment.label);
    return `${pointsText(sprint, unit)}. ${parts.join(", ")}`;
}

export function unestimatedText(count) {
    return count ? _t("%(count)s not estimated", { count }) : "";
}

export function backlogText(backlog) {
    if (!backlog) {
        return "";
    }
    const base = _t("%(count)s issues", { count: backlog.issue_count });
    return backlog.unestimated_count
        ? `${base}, ${unestimatedText(backlog.unestimated_count)}`
        : base;
}

/** The one valid next step for a planned sprint (spec section 12). */
export function planChip(sprint) {
    if (sprint.state !== "draft") {
        return null;
    }
    if (!sprint.planning_confirmed) {
        return { text: _t("Plan not confirmed"), action: "action_confirm_plan", label: _t("Confirm plan"), tone: "" };
    }
    if (sprint.planning_stale) {
        return {
            text: _t("Plan changed since it was confirmed"),
            action: "action_open_scope_change",
            label: _t("Update plan"),
            tone: "danger",
            startBlocked: true,
        };
    }
    return { text: _t("Plan confirmed"), action: "action_agile_open_start", label: _t("Start sprint"), tone: "" };
}

/** How far an epic has come: the bar follows points when it has any, else issues. */
export function epicProgress(epic, unit) {
    const byPoints = epic.points > 0;
    const total = byPoints ? epic.points : epic.children;
    const done = byPoints ? epic.done_points : epic.done_children;
    const percent = total ? Math.min(Math.round((done / total) * 100), 100) : 0;
    const issues = epic.children
        ? _t("%(done)s of %(total)s issues done", { done: epic.done_children, total: epic.children })
        : _t("No issues yet");
    // With Issue count the points are the issues themselves, so the second line would repeat the first.
    const points = epic.points && unit !== "issues"
        ? _t("%(done)s of %(total)s %(unit)s", {
              unit: unitWord(unit),
              done: formatPoints(epic.done_points),
              total: formatPoints(epic.points),
          })
        : "";
    return { percent, issues, points };
}
