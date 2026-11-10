import { describe, expect, test } from "@odoo/hoot";
import { makeTestApp } from "@web/../tests/web_test_helpers";
import {
    ARROW_GAP,
    ROW_H,
    barBox,
    collisionText,
    dependencyLines,
    describeItem,
    nextBarIndex,
    readShowDependencies,
    writeShowDependencies,
    progressText,
    rulerTicks,
    shortDate,
    rollupText,
    timeRange,
    warningText,
    visibleRows,
} from "@agile_community/roadmap/agile_roadmap";

describe.current.tags("desktop");

const epic = (id, start, end, children = [], extra = {}) => ({
    kind: "epic", id, key: `E-${id}`, name: `Epic ${id}`, start, end, done: 1, total: 2, late: false, circular: false, children, ...extra,
});
const issue = (id, start, end, extra = {}) => ({
    kind: "issue", id, key: `I-${id}`, name: `Issue ${id}`, start, end, status: "backlog", late: false, circular: false, ...extra,
});

function data(overrides = {}) {
    return {
        today: "2026-10-10",
        multi: false,
        sprints: [{ id: 1, name: "S1", start: "2026-10-01", end: "2026-10-14" }],
        releases: [{ id: 1, name: "R1", date: "2026-11-30" }],
        dependencies: [],
        projects: [{ id: 1, name: "P", rows: [epic(10, "2026-10-05", "2026-10-20", [issue(1, "2026-10-06", "2026-10-08"), issue(2, "2026-10-12", "2026-10-15")]), epic(11, "2026-10-25", "2026-11-05")] }],
        ...overrides,
    };
}

test("the range holds every date and today with air on both sides", async () => {
    await makeTestApp();
    const range = timeRange(data());
    const day = (iso) => Math.round(Date.parse(`${iso}T00:00:00Z`) / 86400000);
    expect(range.start).toBe(day("2026-10-01") - 7);
    expect(range.end).toBe(day("2026-11-30") + 14);
});

test("a bar starts at its first day and spans both end days", async () => {
    await makeTestApp();
    const range = { start: Math.round(Date.parse("2026-10-01T00:00:00Z") / 86400000), end: 0 };
    expect(barBox(range, "week", "2026-10-03", "2026-10-05")).toEqual({ left: 48, width: 72 });
    expect(barBox(range, "quarter", "2026-10-03", "2026-10-03").width).toBe(6); // never thinner than 6px
});

test("children show only for expanded epics and projects get a heading when several are shown", async () => {
    await makeTestApp();
    const d = data();
    expect(visibleRows(d, new Set()).map((r) => r.type)).toEqual(["epic", "epic"]);
    const open = visibleRows(d, new Set(["epic:10"]));
    expect(open.map((r) => r.type)).toEqual(["epic", "issue", "issue", "epic"]);
    expect(open.map((r) => r.index)).toEqual([0, 1, 2, 3]);
    const multi = visibleRows({ ...d, multi: true }, new Set());
    expect(multi[0].type).toBe("project");
});

test("an arrow runs from the blocker's end to the blocked bar's start, on the epic row when collapsed", async () => {
    await makeTestApp();
    const d = data({ dependencies: [{ from: 11, to: 1, late: true, hidden: false }] });
    const range = timeRange(d);
    const collapsed = visibleRows(d, new Set());
    // Issue 1 sits inside the collapsed epic 10, so the arrow lands on epic 10's row (the first).
    const mid = ROW_H / 2;
    const [line] = dependencyLines(d, collapsed, range, "month");
    const box11 = barBox(range, "month", "2026-10-25", "2026-11-05");
    expect(line.path.startsWith(`M ${box11.left + box11.width} ${ROW_H + mid}`)).toBe(true);
    expect(line.path.includes(`V ${mid} H ${barBox(range, "month", "2026-10-05", "2026-10-20").left}`)).toBe(true);
    // Expanded, it goes to the issue's own row (the second) and starts from epic 11's new place.
    const [inner] = dependencyLines(d, visibleRows(d, new Set(["epic:10"])), range, "month");
    expect(inner.path.startsWith(`M ${box11.left + box11.width} ${3 * ROW_H + mid}`)).toBe(true);
    expect(inner.path.includes(`V ${ROW_H + mid} H ${barBox(range, "month", "2026-10-06", "2026-10-08").left}`)).toBe(true);
});

test("an arrow within one row and a missing target draw nothing, a hidden blocker draws a stub", async () => {
    await makeTestApp();
    const d = data({
        dependencies: [
            { from: 1, to: 2, late: false, hidden: false }, // both inside collapsed epic 10
            { from: 1, to: 99, late: false, hidden: false }, // target not on screen
            { from: null, to: 10, late: false, hidden: true },
        ],
    });
    const lines = dependencyLines(d, visibleRows(d, new Set()), timeRange(d), "month");
    expect(lines.length).toBe(1);
    expect(lines[0].stub).toBe(true);
});

test("text for progress and for a bar names its dates and problems", async () => {
    await makeTestApp();
    expect(progressText(epic(1, "a", "b"))).toBe("1 of 2 done");
    expect(progressText(issue(1, "a", "b"))).toBe("");
    const text = describeItem(epic(1, "2026-10-05", "2026-10-20", [], { late: true }));
    expect(text).toBe("E-1 Epic 1. 2026-10-05 to 2026-10-20. 1 of 2 done. Contains an issue that starts before its blocker ends");
});

test("arrow keys, Home and End pick the next bar and stop at both ends", async () => {
    await makeTestApp();
    expect(nextBarIndex(4, 1, "ArrowDown")).toBe(2);
    expect(nextBarIndex(4, 1, "ArrowRight")).toBe(2);
    expect(nextBarIndex(4, 1, "ArrowUp")).toBe(0);
    expect(nextBarIndex(4, 0, "ArrowUp")).toBe(0);
    expect(nextBarIndex(4, 3, "ArrowDown")).toBe(3);
    expect(nextBarIndex(4, 2, "Home")).toBe(0);
    expect(nextBarIndex(4, 1, "End")).toBe(3);
    expect(nextBarIndex(4, 1, "Enter")).toBe(null);
    expect(nextBarIndex(0, 0, "ArrowDown")).toBe(null);
});

test("a project heading carries its id and progress, and the rollup reads as words", async () => {
    await makeTestApp();
    const rollup = { epics_done: 3, epics_total: 5, issues_done: 18, issues_total: 40 };
    const d = data({ multi: true, projects: [{ id: 7, name: "Shop", rollup, rows: [] }] });
    const [heading] = visibleRows(d, new Set());
    expect(heading).toMatchObject({ type: "project", id: 7, name: "Shop" });
    expect(rollupText(heading.rollup)).toBe("3 of 5 epics done, 18 of 40 issues done");
    expect(rollupText({ epics_done: 0, epics_total: 0, issues_done: 0, issues_total: 0 })).toBe("No issues yet");
});

test("the dependencies switch is on until this browser stored off, and unreadable storage means on", async () => {
    await makeTestApp();
    const memory = new Map();
    const storage = { getItem: (k) => memory.get(k) ?? null, setItem: (k, v) => memory.set(k, v) };
    expect(readShowDependencies(storage)).toBe(true);
    writeShowDependencies(storage, false);
    expect(readShowDependencies(storage)).toBe(false);
    writeShowDependencies(storage, true);
    expect(readShowDependencies(storage)).toBe(true);
    const blocked = {
        getItem: () => {
            throw new Error("blocked");
        },
        setItem: () => {
            throw new Error("blocked");
        },
    };
    expect(readShowDependencies(blocked)).toBe(true);
    writeShowDependencies(blocked, false); // must not throw
});

test("a late bar reads out how many days early it starts and its earliest valid start", async () => {
    await makeTestApp();
    const collision = { blocker_key: "I-9", blocker_end: "2026-10-12", days: 7, earliest_start: "2026-10-13", new_end: "2026-10-17" };
    expect(collisionText(collision)).toBe("Starts 7 days before I-9 ends. Earliest valid start 2026-10-13.");
    expect(collisionText({ ...collision, days: 1 })).toBe("Starts 1 day before I-9 ends. Earliest valid start 2026-10-13.");
    const text = describeItem(issue(3, "2026-10-05", "2026-10-09", { late: true, collision }));
    expect(text).toBe("I-3 Issue 3. 2026-10-05 to 2026-10-09. Starts 7 days before I-9 ends. Earliest valid start 2026-10-13.");
});

test("the ruler marks every Monday, or the first of each month when zoomed out", async () => {
    await makeTestApp();
    const day = (iso) => Math.round(Date.parse(`${iso}T00:00:00Z`) / 86400000);
    const range = { start: day("2026-10-26"), end: day("2026-11-30") }; // a Monday up to a Monday
    const weeks = rulerTicks(range, "month");
    expect(weeks.length).toBe(6);
    expect(weeks[0].left).toBe(0);
    expect(weeks[1].left).toBe(7 * 8);
    expect(weeks[1].label).toMatch(/2/);
    const months = rulerTicks(range, "quarter");
    expect(months.map((t) => t.left)).toEqual([6 * 3]); // 1 Nov is six days in
    expect(months[0].month).toBe(true);
    expect(shortDate("2026-11-03")).toMatch(/3/);
});

test("an arrow to a bar that starts before the blocker ends runs along the row edge, not across the bar", async () => {
    await makeTestApp();
    const d = data({
        dependencies: [{ from: 11, to: 2, late: true, hidden: false }],
    });
    const range = timeRange(d);
    const rows = visibleRows(d, new Set(["epic:10"]));
    const [line] = dependencyLines(d, rows, range, "month");
    const from = barBox(range, "month", "2026-10-25", "2026-11-05");
    const to = barBox(range, "month", "2026-10-12", "2026-10-15");
    const toRow = rows.find((r) => r.item?.id === 2);
    const edge = toRow.index * ROW_H;
    expect(line.path).toBe(
        `M ${from.left + from.width} ${3 * ROW_H + ROW_H / 2} H ${from.left + from.width + ARROW_GAP} V ${edge + ROW_H} H ${to.left - ARROW_GAP} V ${toRow.index * ROW_H + ROW_H / 2} H ${to.left}`
    );
});

test("the warning popover words follow the design: title, days, dates, earliest start and where the end goes", async () => {
    await makeTestApp();
    const collision = { blocker_id: 9, blocker_key: "I-9", blocker_end: "2026-10-12", days: 7, earliest_start: "2026-10-13", new_end: "2026-10-17" };
    const words = warningText(issue(3, "2026-10-05", "2026-10-09", { late: true, collision }));
    expect(words.title).toBe("I-3 starts too early");
    expect(words.lead).toBe("Starts 7 days before I-9 ends.");
    expect(words.detail).toMatch(/^I-9 ends .*12.*; I-3 starts .*5.*\.$/);
    expect(words.earliest).toMatch(/^Earliest valid start: .*13.*\(the day after the last blocker ends\)\. Moving the start keeps the length, so the end moves from .*9.* to .*17.*\.$/);
    const open = warningText(issue(4, "2026-10-05", "2026-10-09", { collision: { ...collision, days: 1, new_end: null } }));
    expect(open.lead).toBe("Starts 1 day before I-9 ends.");
    expect(open.earliest).not.toMatch(/Moving/);
});
