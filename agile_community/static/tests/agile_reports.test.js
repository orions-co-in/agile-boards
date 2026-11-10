import { markup } from "@odoo/owl";
import { describe, expect, test } from "@odoo/hoot";
import { click, queryAllTexts, waitFor } from "@odoo/hoot-dom";
import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { WebClient } from "@web/webclient/webclient";
import { defineModels, getService, makeTestApp, models, contains, mountWithCleanup, onRpc } from "@web/../tests/web_test_helpers";
import { niceMax, stackLayout } from "@agile_community/reports/agile_cfd";
import { burndownLayout, leftText } from "@agile_community/reports/agile_burndown";
import { deliveredText, groupText, withMarkedHelp } from "@agile_community/reports/agile_reports";
import { burnupLayout, doneText } from "@agile_community/reports/agile_burnup";
import { controlLayout, controlText } from "@agile_community/reports/agile_control";
import { deployLayout, deploySummary } from "@agile_community/reports/agile_deploys";
import { csvCell, csvText, reportFileName, sprintPngBlob, svgPngBlob } from "@agile_community/reports/report_export";

describe.current.tags("desktop");

class AgileReportModel extends models.Model {
    _name = "agile.report";
}

defineMailModels();
defineModels([AgileReportModel]);

const STATUSES = [
    { code: "done", label: "Done" },
    { code: "backlog", label: "Backlog" },
];

test("the axis tops out at 1, 2, 5 or 10 times a power of ten", async () => {
    await makeTestApp();
    expect([0, 1, 3, 7, 12, 34, 101].map(niceMax)).toEqual([1, 1, 5, 10, 20, 50, 200]);
});

test("bands stack from the first status upward and add up to the day's total", async () => {
    await makeTestApp();
    const days = [
        { date: "2026-10-01", counts: { done: 1, backlog: 3 }, total: 4 },
        { date: "2026-10-02", counts: { done: 2, backlog: 2 }, total: 4 },
    ];
    const layout = stackLayout(days, STATUSES);
    expect(layout.top).toBe(5);
    expect(layout.bands.map((b) => b.code)).toEqual(["done", "backlog"]);
    expect(layout.bands[0].lower).toEqual([0, 0]);
    expect(layout.bands[0].upper).toEqual([1, 2]);
    expect(layout.bands[1].lower).toEqual([1, 2]);
    expect(layout.bands[1].upper).toEqual([4, 4]);
    // The top band reaches the day's total, and a point per day on each edge.
    expect(layout.bands[1].points.split(" ").length).toBe(4);
    expect(layout.y(4) < layout.y(1)).toBe(true);
    // A single day is still drawn.
    expect(stackLayout([days[0]], STATUSES).bands[0].points.split(" ").length).toBe(2);
});

test("the sprint report sentences say what was delivered and what is hidden", async () => {
    await makeTestApp();
    expect(deliveredText({ planned_points: 24, completed_points: 21, percent: 88 }, false)).toBe(
        "Delivered 21 of 24 planned points, 88%"
    );
    expect(deliveredText({ planned_points: 24, completed_points: 3, percent: 13 }, true)).toBe(
        "Delivered so far 3 of 24 planned points, 13%"
    );
    expect(deliveredText({ planned_points: 0, completed_points: 0, percent: null }, false)).toBe(
        "No points were planned at the start."
    );
    expect(groupText({ count: 1, points: 3, hidden: 0 })).toBe("1 issue, 3 points");
    expect(groupText({ count: 4, points: 12, hidden: 2 })).toBe("4 issues, 12 points (2 you cannot see)");
});

test("the burndown draws points left as an area and the scope as a stepped line", async () => {
    await makeTestApp();
    const days = [
        { date: "2026-10-01", remaining: 8, scope: 8, done: 0, issues: 2 },
        { date: "2026-10-02", remaining: 5, scope: 10, done: 5, issues: 3 },
    ];
    const layout = burndownLayout(days);
    expect(layout.top).toBe(10);
    // Remaining touches the day's value; the area closes along the axis.
    expect(layout.remainingLine.split(" ").length).toBe(2);
    expect(layout.area.split(" ").length).toBe(4);
    // The scope steps: hold at 8 until day two, then rise to 10 (three points for two days).
    expect(layout.scopeLine.split(" ").length).toBe(3);
    expect(layout.y(8) > layout.y(10)).toBe(true);
    expect(leftText(days[1], 0)).toBe("5 of 10 points left");
    expect(leftText(days[1], 2)).toBe("5 of 10 points left. 2 issues have no estimate yet.");
});

// Mounting the whole web client is slow on a busy database, so this gets a longer limit.
test.timeout(20000);
test("the sprint picker lists every sprint by its own name", async () => {
    const group = { count: 0, points: 0, hidden: 0, issues: [] };
    onRpc("agile.report", "reports_meta", () => ({
        reports: [{ code: "sprint", group: "Sprint", label: "Sprint report", question: "" }],
        epics: [],
        releases: [],
        sprints: [
            { id: 3, name: "Sprint 3", state: "in_progress", date_start: "2026-11-03", date_end: "2026-11-16" },
            { id: 2, name: "Sprint 2", state: "in_progress", date_start: "2026-10-20", date_end: "2026-11-02" },
            { id: 4, name: "Sprint 4", state: "draft", date_start: "2026-11-17", date_end: "2026-11-30" },
        ],
    }));
    onRpc("agile.report", "sprint_report", () => ({
        sprint: { id: 3, name: "Sprint 3", state: "in_progress", goal: "", retro_notes: "", date_start: "2026-11-03", date_end: "2026-11-16" },
        retro_actions: [],
        previous_actions: { sprint: false, actions: [] },
        can_manage: false,
        so_far: true,
        groups: { completed: group, carried: group, added: group, removed: group, planned: group },
        no_plan: false,
        delivered: { planned_points: 0, completed_points: 0, percent: 0 },
    }));
    await mountWithCleanup(WebClient);
    await getService("action").doAction({ type: "ir.actions.client", tag: "agile_community.reports", params: { project_id: 1 } });
    await waitFor(".o_ag_reports_head select");
    expect(queryAllTexts(".o_ag_reports_head select option")).toEqual(["Sprint 3 (active)", "Sprint 2 (active)", "Sprint 4 (planned)"]);
});

test("a manager adds a retrospective action and the previous sprint's open ones are listed", async () => {
    const group = { count: 0, points: 0, hidden: 0, issues: [] };
    const added = [];
    onRpc("agile.report", "reports_meta", () => ({
        reports: [{ code: "sprint", group: "Sprint", label: "Sprint report", question: "" }],
        epics: [],
        releases: [],
        sprints: [{ id: 3, name: "Sprint 3", state: "in_progress", date_start: "2026-11-03", date_end: "2026-11-16" }],
    }));
    onRpc("agile.report", "sprint_report", () => ({
        sprint: { id: 3, name: "Sprint 3", state: "in_progress", goal: "", retro_notes: "", date_start: "2026-11-03", date_end: "2026-11-16" },
        retro_actions: added.map((name, id) => ({ id: id + 1, key: "K-" + (id + 1), name, status: "Backlog", open: true })),
        previous_actions: { sprint: { id: 2, name: "Sprint 2" }, actions: [{ id: 9, key: "K-9", name: "Fix flaky build", status: "To Do", open: true }] },
        can_manage: true,
        so_far: true,
        groups: { completed: group, carried: group, added: group, removed: group, planned: group },
        no_plan: false,
        delivered: { planned_points: 0, completed_points: 0, percent: 0 },
    }));
    onRpc("project.sprint", "agile_retro_add_action", ({ args }) => {
        added.push(args[1]);
        return { id: added.length, key: "K-" + added.length, name: args[1] };
    });
    await mountWithCleanup(WebClient);
    await getService("action").doAction({ type: "ir.actions.client", tag: "agile_community.reports", params: { project_id: 1 } });
    await waitFor(".o_ag_reports_action_form input");
    expect(queryAllTexts(".o_ag_reports_previous h3")).toEqual(["Open actions from Sprint 2"]);
    await contains(".o_ag_reports_action_form input").edit("Shorten stand-ups");
    await click(".o_ag_reports_action_form button");
    await waitFor(".o_ag_reports_retro:not(.o_ag_reports_previous) .o_ag_reports_actions li");
    expect(added).toEqual(["Shorten stand-ups"]);
    expect(queryAllTexts(".o_ag_reports_retro:not(.o_ag_reports_previous) .o_ag_reports_actions li")).toEqual(["K-1 Shorten stand-ups\nBacklog"]);
});

test("burnup draws done as a rising line and the scope as steps, and words the scope change", async () => {
    await makeTestApp();
    const days = [
        { date: "2026-10-05", done: 0, scope: 10 },
        { date: "2026-10-06", done: 4, scope: 10 },
        { date: "2026-10-07", done: 6, scope: 14 },
    ];
    const layout = burnupLayout(days);
    expect(layout.doneLine.split(" ").length).toBe(3);
    // The scope holds until the day it changes: two points for the step, one for the first day.
    expect(layout.scopeLine.split(" ").length).toBe(5);
    expect(layout.y(6) < layout.y(4)).toBe(true);
    expect(String(doneText(days, "points"))).toBe("6 of 14 points done. The scope grew by 4 since 2026-10-05.");
    expect(burnupLayout(days.slice(0, 1)).scopeLine.split(" ").length).toBe(3);
    expect(String(doneText(days.slice(0, 2), "hours"))).toBe("4 of 10 hours done");
});

test("control chart places a dot per issue by finish date and words the average", async () => {
    await makeTestApp();
    const data = {
        from: "2026-10-01", to: "2026-10-31", window: 5, average: 4, longest: 6, hidden: 0,
        issues: [
            { key: "A-1", name: "One", date: "2026-10-05", days: 2, rolling: 2 },
            { key: "A-2", name: "Two", date: "2026-10-20", days: 6, rolling: 4 },
        ],
    };
    const layout = controlLayout(data);
    expect(layout.dots.length).toBe(2);
    expect(layout.dots[1].cx > layout.dots[0].cx).toBe(true);
    expect(layout.dots[1].cy < layout.dots[0].cy).toBe(true);
    expect(layout.rollingLine.split(" ").length).toBe(2);
    expect(String(controlText(data))).toBe("2 issues finished, 4 days on average, the longest 6 days");
    expect(String(controlText({ ...data, issues: [] }))).toBe("No issue with a start and a finish in this range.");
});

test("a CSV cell is quoted when needed and a spreadsheet formula is made harmless", () => {
    expect(csvCell("plain")).toBe("plain");
    expect(csvCell('say "hi", ok')).toBe('"say ""hi"", ok"');
    expect(csvCell("=SUM(A1)")).toBe("'=SUM(A1)");
    expect(csvCell("@cmd")).toBe("'@cmd");
    expect(csvCell(-3)).toBe("-3");
    expect(csvCell(null)).toBe("");
    expect(csvCell(false)).toBe("");
    expect(csvCell(0)).toBe("0");
});

test("a report's numbers become one header line and one line per row", () => {
    expect(csvText(["Day", "Done"], [["2026-11-01", 3], ["2026-11-02", 5]])).toBe("Day,Done\r\n2026-11-01,3\r\n2026-11-02,5\r\n");
});

test("a report file is named after its title and the day", () => {
    expect(reportFileName("Sprint 1 burnup", "csv", new Date("2026-11-02T10:00:00Z"))).toBe("sprint-1-burnup-2026-11-02.csv");
});

test("the sprint report and a chart both become a PNG", async () => {
    const sprint = await sprintPngBlob("Sprint 1 report", "Delivered 3 of 4", [{ label: "Planned", percent: 100, text: "4 pts" }, { label: "Delivered", percent: 75, text: "3 pts" }], [{ count: 3, label: "Completed", text: "3 issues, 3 pts" }]);
    expect(sprint.type).toBe("image/png");
    expect(sprint.size).toBeGreaterThan(500);
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 200 100");
    svg.innerHTML = '<rect x="10" y="10" width="80" height="40" fill="#714b67"/>';
    document.body.appendChild(svg);
    const chart = await svgPngBlob(svg, "Chart", "sub");
    svg.remove();
    expect(chart.type).toBe("image/png");
    expect(chart.size).toBeGreaterThan(500);
});

test("deployment columns stand on a nice top and stack failures above successes", () => {
    const layout = deployLayout([{ date: "2026-10-05", count: 4, failed: 1 }, { date: "2026-10-12", count: 0, failed: 0 }]);
    expect(layout.top).toBe(5);
    expect(layout.bars.length).toBe(2);
    expect(layout.bars[0].doneHeight).toBeGreaterThan(layout.bars[0].failedHeight);
    expect(layout.bars[1].doneHeight).toBe(0);
    expect(layout.bars[0].failedY).toBeLessThan(layout.bars[0].doneY);
});

test("the deployment summary says what happened, or what to do when nothing was recorded", async () => {
    await makeTestApp();
    expect(deploySummary({ any: false })).toMatch(/No deployments have been recorded/);
    expect(deploySummary({ any: true, total: 0, environment: "production" })).toMatch(/No deploys to production/);
    const text = deploySummary({ any: true, total: 12, environment: "production", per_week: 1.2, days_since: 3, failed: 2 });
    expect(text).toBe("12 deploys to production, about 1.2 a week. The last one was 3 days ago. 2 failed.");
    expect(deploySummary({ any: true, total: 1, environment: "", per_week: 0.1, days_since: 0, failed: 0 })).toMatch(/today/);
});

test("an action's empty-state help is marked as markup so the tags are not printed (NU-33)", () => {
    const action = withMarkedHelp({ name: "Velocity", help: "<p>No completed sprints yet</p>" });
    expect(String(action.help)).toBe("<p>No completed sprints yet</p>");
    expect(action.help instanceof markup("").constructor).toBe(true); // a Markup, not a plain string
    expect(withMarkedHelp({ name: "x" }).help).toBe(undefined);
});
