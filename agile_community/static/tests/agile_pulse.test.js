import { describe, expect, test } from "@odoo/hoot";
import { click, queryAll, queryAllTexts, queryOne, press, waitFor, waitForNone } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import {
    getService,
    mountWithCleanup,
    onRpc,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { WebClient } from "@web/webclient/webclient";
import { AgilePulse } from "@agile_community/components/pulse/agile_pulse";

describe.current.tags("desktop");

defineMailModels();

const SPRINT = {
    id: 5,
    name: "Sprint 14",
    state: "in_progress",
    date_start: "2026-10-05",
    date_end: "2026-10-16",
    committed_points: 30,
    planned_points: 30,
    capacity_points: 28,
    completed_points: 0,
    total_days: 12,
};

function day(date, n, extra = {}) {
    return {
        date,
        day_number: n,
        is_weekend: false,
        is_today: false,
        is_future: false,
        points_left: 30,
        estimated: false,
        ideal_left: 30,
        scope_changed: false,
        scope_points: 0,
        ...extra,
    };
}

function activePayload(overrides = {}) {
    return {
        state: "active",
        today: "2026-10-07",
        project: { id: 7, name: "Walkthrough Agile" },
        counts: { open: 8, blocked: 1, overdue: 3, review: 2 },
        sprint: SPRINT,
        days: [
            day("2026-10-05", 1, { points_left: 30, ideal_left: 30 }),
            day("2026-10-06", 2, { points_left: 27, ideal_left: 26.67 }),
            day("2026-10-07", 3, {
                is_today: true,
                points_left: 24,
                ideal_left: 23.33,
                scope_changed: true,
                scope_points: 3,
            }),
            day("2026-10-08", 4, { is_future: true, points_left: null, ideal_left: 20 }),
            day("2026-10-10", 6, { is_future: true, is_weekend: true, points_left: null, ideal_left: 16 }),
        ],
        pace: { points_left: 16, ideal_left: 9, delta: 7, status: "behind" },
        scope_changes: [{ date: "2026-10-07", points_delta: 3 }],
        can_manage: true,
        can_manage_project: true,
        ...overrides,
    };
}

test("active strip marks today, future days and scope changes with shapes and words", async () => {
    await mountWithCleanup(AgilePulse, { props: { pulse: activePayload() } });
    expect(".o_ag_pulse_cell").toHaveCount(5);
    expect(".o_ag_pulse_today").toHaveCount(1);
    expect(".o_ag_pulse_future").toHaveCount(2);
    expect(".o_ag_pulse_weekend").toHaveCount(1);
    expect(".o_ag_pulse_scope").toHaveCount(1);
    const caption = queryAllTexts(".o_ag_pulse_caption > *");
    expect(caption[0]).toBe("Sprint 14 day 3 of 12");
    expect(caption[1]).toBe("16 points left, ideal 9: behind by 7");
    expect(caption[2]).toBe("1 scope change on day 3 (+3)");
    expect(".o_ag_pace_behind").toHaveCount(1);
});

test("pace is ahead, on pace or behind in words", async () => {
    const pulse = activePayload({ pace: { points_left: 8, ideal_left: 9, delta: -1, status: "on_pace" } });
    await mountWithCleanup(AgilePulse, { props: { pulse } });
    expect(queryAllTexts(".o_ag_pulse_caption > *")[1]).toBe("8 points left, ideal 9: on pace");
    expect(".o_ag_pace_behind").toHaveCount(0);
});

test("ahead of pace reads as ahead and several scope changes show the net", async () => {
    const pulse = activePayload({
        pace: { points_left: 5, ideal_left: 9, delta: -4, status: "ahead" },
        scope_changes: [
            { date: "2026-10-06", points_delta: 3 },
            { date: "2026-10-07", points_delta: -1 },
        ],
    });
    await mountWithCleanup(AgilePulse, { props: { pulse } });
    const caption = queryAllTexts(".o_ag_pulse_caption > *");
    expect(caption[1]).toBe("5 points left, ideal 9: ahead by 4");
    expect(caption[2]).toBe("2 scope changes, net +2");
});

test("no scope changes says so", async () => {
    const pulse = activePayload({ scope_changes: [] });
    await mountWithCleanup(AgilePulse, { props: { pulse } });
    expect(queryAllTexts(".o_ag_pulse_caption > *")[2]).toBe("No scope changes");
});

test("strip exposes a text alternative: group label and a data table", async () => {
    await mountWithCleanup(AgilePulse, { props: { pulse: activePayload() } });
    expect(".o_ag_pulse_strip").toHaveAttribute("role", "group");
    expect(queryOne(".o_ag_pulse_strip").getAttribute("aria-label")).toInclude("behind by 7");
    expect("table.visually-hidden tbody tr").toHaveCount(5);
    expect(queryAll(".o_ag_pulse_cell").every((cell) => cell.getAttribute("aria-label"))).toBe(true);
});

test("arrow keys move between days with one tab stop and show the day in the tip", async () => {
    await mountWithCleanup(AgilePulse, { props: { pulse: activePayload() } });
    expect(".o_ag_pulse_cell[tabindex='0']").toHaveCount(1);
    expect(".o_ag_pulse_today").toHaveAttribute("tabindex", "0");
    queryOne(".o_ag_pulse_today").focus();
    await animationFrame();
    await press("ArrowRight");
    await animationFrame();
    expect(".o_ag_pulse_tip").toHaveText(/ideal 20 points left/);
    await press("Home");
    await animationFrame();
    expect(".o_ag_pulse_tip").toHaveText(/30 points left, ideal 30/);
    await press("End");
    await animationFrame();
    expect(".o_ag_pulse_tip").toHaveText(/ideal 16 points left/);
});

test("planned sprint shows planned points, capacity and a start link only for managers", async () => {
    const planned = {
        ...activePayload(),
        state: "planned",
        today: "2026-10-01",
        days: [],
        pace: null,
        scope_changes: [],
        sprint: { ...SPRINT, state: "draft", planned_points: 24 },
    };
    let opened = null;
    await mountWithCleanup(AgilePulse, {
        props: { pulse: planned, onOpenSprint: (id) => (opened = id) },
    });
    expect(".o_ag_pulse_cell").toHaveCount(12);
    expect(".o_ag_pulse_future").toHaveCount(12);
    const caption = queryAllTexts(".o_ag_pulse_caption > *");
    expect(caption[0]).toMatch(/^Sprint 14 starts /);
    expect(caption[1]).toBe("24 points planned, team capacity 28");
    expect(caption[2]).toBe("Start the sprint");
    await click(".o_ag_pulse_link:last-child");
    expect(opened).toBe(5);
});

test("planned sprint hides the start link from non managers", async () => {
    const planned = {
        ...activePayload({ can_manage: false }),
        state: "planned",
        days: [],
        pace: null,
        sprint: { ...SPRINT, state: "draft" },
    };
    await mountWithCleanup(AgilePulse, { props: { pulse: planned } });
    expect(queryAllTexts(".o_ag_pulse_caption > *")).not.toInclude("Start the sprint");
});

test("day one without a snapshot waits instead of inventing a pace", async () => {
    const waiting = {
        ...activePayload(),
        state: "waiting",
        today: "2026-10-05",
        days: [],
        pace: null,
        scope_changes: [],
    };
    await mountWithCleanup(AgilePulse, { props: { pulse: waiting } });
    const caption = queryAllTexts(".o_ag_pulse_caption > *");
    expect(caption).toEqual([
        "Sprint 14 day 1 of 12",
        "Waiting for the first daily snapshot",
        "Pace shows from day 2",
    ]);
    expect(".o_ag_pulse_today").toHaveCount(1);
});

test("completed sprint reports done and carried over points", async () => {
    const completed = {
        ...activePayload(),
        state: "completed",
        pace: null,
        sprint: { ...SPRINT, state: "done", completed_points: 26, committed_points: 30 },
    };
    await mountWithCleanup(AgilePulse, { props: { pulse: completed } });
    expect(queryAllTexts(".o_ag_pulse_caption > *")).toEqual([
        "Sprint 14 completed",
        "26 of 30 points done",
        "4 points carried over",
    ]);
});

test("no sprint offers planning to managers and nothing for kanban projects", async () => {
    let planned = false;
    const none = { ...activePayload(), state: "none", sprint: false, days: [], pace: null };
    await mountWithCleanup(AgilePulse, { props: { pulse: none, onPlanSprint: () => (planned = true) } });
    expect(".o_ag_pulse_empty").toHaveCount(1);
    expect(".o_ag_pulse_empty").toHaveText(/No active sprint/);
    await click(".o_ag_pulse_empty .btn-primary");
    expect(planned).toBe(true);
});

test("kanban projects render no strip", async () => {
    await mountWithCleanup(AgilePulse, {
        props: { pulse: { ...activePayload(), state: "kanban", sprint: false, days: [] } },
    });
    expect(".o_ag_pulse").toHaveCount(0);
});

async function openOverview(action = {}) {
    await mountWithCleanup(WebClient);
    const actionService = getService("action");
    const opened = [];
    patchWithCleanup(actionService, {
        doActionButton(params) {
            opened.push(params);
            return Promise.resolve();
        },
    });
    await actionService.doAction({
        type: "ir.actions.client",
        tag: "agile_community.overview",
        params: { project_id: 7 },
        ...action,
    });
    return opened;
}

test("overview loads the pulse and tiles drill into the matching list", async () => {
    onRpc("project.project", "agile_pulse_data", () => activePayload());
    const opened = await openOverview();
    await waitFor(".o_ag_overview_title");
    expect(".o_ag_overview_title").toHaveText("Walkthrough Agile");
    expect(queryAllTexts(".o_ag_tile_count")).toEqual(["8", "1", "3", "2"]);
    expect(queryAllTexts(".o_ag_tile_label")).toEqual(["Open issues", "Blocked", "Overdue", "In review"]);
    expect(".o_ag_pulse").toHaveCount(1);
    await click(".o_ag_tile[data-metric='blocked']");
    await animationFrame();
    expect(opened).toHaveLength(1);
    expect(opened[0].name).toBe("action_view_agile_metric_issues");
    expect(opened[0].resModel).toBe("project.project");
    expect(opened[0].resId).toBe(7);
    expect(opened[0].context).toEqual({ agile_metric_filter: "blocked" });
    await click(".o_ag_overview_head .btn-link");
    await animationFrame();
    expect(opened.at(-1).name).toBe("action_view_agile_reports");
});

test("overview shows an error with retry, then recovers", async () => {
    let calls = 0;
    onRpc("project.project", "agile_pulse_data", () => {
        calls++;
        if (calls === 1) {
            throw new Error("You must be a member of this Agile project to view its delivery metrics.");
        }
        return activePayload();
    });
    await openOverview();
    await waitFor(".o_ag_overview_error");
    expect(".o_ag_overview_error").toHaveText(/member of this Agile project/);
    await click(".o_ag_overview_error .btn");
    await waitForNone(".o_ag_overview_error");
    await waitFor(".o_ag_pulse");
    expect(calls).toBe(2);
});

test("overview resolves the project from the action context as a fallback", async () => {
    const seen = [];
    onRpc("project.project", "agile_pulse_data", ({ args }) => {
        seen.push(args[0][0]);
        return activePayload();
    });
    await openOverview({ params: undefined, context: { active_id: 9 } });
    await waitFor(".o_ag_overview_title");
    expect(seen).toEqual([9]);
});
