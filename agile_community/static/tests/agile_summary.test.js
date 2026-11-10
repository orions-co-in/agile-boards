import { describe, expect, test } from "@odoo/hoot";
import { makeTestApp } from "@web/../tests/web_test_helpers";
import { ago, barWidth, cumulative, flowLines } from "@agile_community/summary/summary_helpers";
import { DEFAULT_LAYOUT, TILE_NAMES, dropInLayout, moveInLayout } from "@agile_community/summary/agile_summary";

describe.current.tags("desktop");

test("running totals add up day by day", () => {
    expect(cumulative([1, 0, 2, 3])).toEqual([1, 1, 3, 6]);
    expect(cumulative([])).toEqual([]);
});

test("both flow lines share one scale and report their totals", () => {
    const flow = { days: ["a", "b", "c"], created: [2, 2, 0], resolved: [0, 1, 1] };
    const lines = flowLines(flow);
    expect(lines.createdTotal).toBe(4);
    expect(lines.resolvedTotal).toBe(2);
    expect(lines.created.split(" ").length).toBe(3);
    // The created line ends at the top (max 4), the resolved line at half height.
    const lastY = (points) => Number(points.split(" ").at(-1).split(",")[1]);
    expect(lastY(lines.created)).toBeLessThan(lastY(lines.resolved));
});

test("the chart carries axis numbers and one readout per day", () => {
    const lines = flowLines({ days: ["2026-10-01", "2026-10-02", "2026-10-03"], created: [2, 2, 0], resolved: [0, 1, 1] });
    expect(lines.yTicks.map((tick) => tick.label)).toEqual(["0", "2", "4"]);
    expect(lines.xTicks).toHaveLength(3);
    expect(lines.days.map((day) => [day.created, day.resolved])).toEqual([[2, 0], [4, 1], [4, 2]]);
});

test("an empty flow does not divide by zero", () => {
    const lines = flowLines({ days: ["a"], created: [0], resolved: [0] });
    expect(lines.createdTotal).toBe(0);
    expect(lines.created).toMatch(/^[\d.]+,[\d.]+$/);
});

test("bar widths are percentages, with a visible minimum", () => {
    expect(barWidth(5, 10)).toBe(50);
    expect(barWidth(1, 1000)).toBe(2);
    expect(barWidth(0, 10)).toBe(0);
    expect(barWidth(3, 0)).toBe(0);
});

test("relative times read like words", () => {
    const now = Date.UTC(2026, 9, 28, 12, 0, 0);
    expect(ago("2026-10-28 11:59:30", now)).toBe("just now");
    expect(ago("2026-10-28 11:48:00", now)).toBe("12 min ago");
    expect(ago("2026-10-28 09:00:00", now)).toBe("3 h ago");
    expect(ago("2026-10-27 12:00:00", now)).toBe("yesterday");
    expect(ago("2026-10-24 12:00:00", now)).toBe("4 days ago");
});

const ids = (layout) => layout.map((tile) => tile.id);

test("every default tile has a name and shows", async () => {
    await makeTestApp();
    expect(ids(DEFAULT_LAYOUT)).toEqual(Object.keys(TILE_NAMES));
    expect(DEFAULT_LAYOUT.every((tile) => !tile.hidden)).toBe(true);
    expect(ids(DEFAULT_LAYOUT)).toHaveLength(9);
});

test("moving a tile swaps it with its shown neighbour and skips hidden ones", async () => {
    await makeTestApp();
    const layout = DEFAULT_LAYOUT.map((tile) => ({ ...tile, hidden: tile.id === "flow" }));
    const moved = moveInLayout(layout, "load", -1);
    // Created and resolved is hidden, so Workload trades places with Status, the shown tile before it.
    expect(ids(moved).slice(0, 5)).toEqual(["pulse", "counts", "load", "flow", "status"]);
    expect(moveInLayout(layout, "pulse", -1)).toBe(layout);
    expect(moveInLayout(layout, "activity", 1)).toBe(layout);
});

test("dropping a tile puts it in front of the target", async () => {
    await makeTestApp();
    const dropped = dropInLayout(DEFAULT_LAYOUT, "activity", "status");
    expect(ids(dropped).slice(0, 4)).toEqual(["pulse", "counts", "activity", "status"]);
    expect(ids(dropped)).toHaveLength(9);
    expect(dropInLayout(DEFAULT_LAYOUT, "status", "status")).toBe(DEFAULT_LAYOUT);
});
