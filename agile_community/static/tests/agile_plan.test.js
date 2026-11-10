import { describe, expect, test } from "@odoo/hoot";
import { makeTestApp } from "@web/../tests/web_test_helpers";
import { planDates, planRows } from "@agile_community/roadmap/agile_plan";
import { compareBars, compareSummary } from "@agile_community/roadmap/agile_plan_scenario";
import { cellText, connectorPath, neighbourOrdinal } from "@agile_community/roadmap/agile_plan_board";

describe.current.tags("desktop");

const epic = (id) => ({ id, key: `E-${id}`, name: `Epic ${id}` });
const item = (id, level, extra = {}) => ({
    id, level, name: `Item ${id}`, start: null, end: null, rolled_start: null, rolled_end: null, epics: [], children: [], ...extra,
});

test("planRows lists each item, then its initiatives and epics, with depth", () => {
    const initiative = item(2, "initiative", { epics: [epic(7), epic(8)] });
    const theme = item(1, "theme", { children: [initiative] });
    const rows = planRows([theme], new Set());
    expect(rows.map((r) => [r.type, r.depth, r.item.id, r.epic?.id])).toEqual([
        ["item", 0, 1, undefined],
        ["item", 1, 2, undefined],
        ["epic", 2, 2, 7],
        ["epic", 2, 2, 8],
    ]);
});

test("a closed item hides what is under it", () => {
    const theme = item(1, "theme", { children: [item(2, "initiative", { epics: [epic(7)] })], epics: [epic(9)] });
    expect(planRows([theme], new Set([1])).length).toBe(1);
    expect(planRows([theme], new Set([2])).length).toBe(3);
});

test("planDates prefers a typed date and marks rolled ones as from epics", () => {
    expect(planDates(item(1, "initiative"))).toBe(null);
    const rolled = planDates(item(1, "initiative", { rolled_start: "2026-11-03", rolled_end: "2026-12-19" }));
    expect(rolled.fromEpics).toBe(true);
    const typed = planDates(item(1, "initiative", { start: "2026-10-01", end: "2026-12-19", rolled_start: "2026-11-03", rolled_end: "2026-12-19" }));
    expect(typed.fromEpics).toBe(false);
    const mixed = planDates(item(1, "initiative", { start: "2026-10-01", rolled_start: "2026-11-03", rolled_end: "2026-12-19" }));
    expect(mixed.fromEpics).toBe(true);
});

test("compareBars puts live and scenario bars on one scale and flags a later end", () => {
    const row = (id, extra) => ({ epic_id: id, live_start: "2026-11-01", live_end: "2026-11-10", start: "2026-11-01", end: "2026-11-10", changed: false, later_days: 0, ...extra });
    const bars = compareBars([row(1), row(2, { end: "2026-11-30", changed: true, later_days: 20 }), row(3, { start: null, end: null })]);
    expect(bars.length).toBe(3);
    expect(bars[0].live.left).toBe(0);
    expect(bars[0].live.width).toBeLessThan(bars[1].scenario.width);
    expect(bars[0].later).toBe(false);
    expect(bars[1].later).toBe(true);
    expect(bars[2].scenario).toBe(null);
    expect(compareBars([])).toEqual([]);
});

test("compareSummary says how many epics move and how many are late", async () => {
    await makeTestApp();
    expect(compareSummary({ moves: 0, late: 0 })).toBe("Nothing differs from the live plan.");
    expect(compareSummary({ moves: 1, late: 0 })).toBe("1 epic moves");
    expect(compareSummary({ moves: 12, late: 3 })).toBe("12 epics move, 3 later than 30 days");
});

test("cellText says planned against capacity and by how much a sprint is over", async () => {
    await makeTestApp();
    expect(cellText(null)).toBe("No sprint");
    expect(cellText({ planned: 0, capacity: 0, over: 0 })).toBe("No capacity set");
    expect(cellText({ planned: 7, capacity: 0, over: 0 })).toBe("7 points planned, no capacity set");
    expect(cellText({ planned: 24, capacity: 30, over: 0 })).toBe("24 of 30 points");
    expect(cellText({ planned: 34, capacity: 30, over: 4 })).toBe("34 of 30 points: over by 4");
});

test("Alt+Left and Alt+Right pick the neighbouring sprint and stop at the ends", () => {
    const card = { ordinal: 1 };
    expect(neighbourOrdinal(card, "ArrowRight", 3)).toBe(2);
    expect(neighbourOrdinal(card, "ArrowLeft", 3)).toBe(0);
    expect(neighbourOrdinal({ ordinal: 0 }, "ArrowLeft", 3)).toBe(null);
    expect(neighbourOrdinal({ ordinal: 2 }, "ArrowRight", 3)).toBe(null);
    expect(neighbourOrdinal(card, "ArrowUp", 3)).toBe(null);
});

test("connectorPath curves from one card edge to the next", () => {
    expect(connectorPath({ x: 10, y: 20 }, { x: 110, y: 80 })).toBe("M 10 20 C 60 20, 60 80, 110 80");
    expect(connectorPath({ x: 10, y: 20 }, { x: 14, y: 20 })).toBe("M 10 20 C 34 20, -10 20, 14 20");
});
