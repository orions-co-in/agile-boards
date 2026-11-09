import { describe, expect, test } from "@odoo/hoot";
import { makeMockEnv } from "@web/../tests/web_test_helpers";
import {
    RELEASE_COLOURS,
    barColour,
    colourLegend,
    releaseColours,
    shareIdFrom,
    shareLink,
} from "@agile_community/roadmap/agile_roadmap_share";

describe.current.tags("desktop");

const item = (id, status, release_id = false, release = "", start = "2026-11-01") => ({ id, status, release_id, release, start, children: [] });
const data = {
    projects: [
        {
            rows: [
                { ...item(1, "progress", 7, "R2"), children: [item(2, "done", 5, "R1"), item(3, "ready")] },
                item(4, "backlog", 7, "R2"),
            ],
        },
    ],
};

test("releases get one colour each, in name order, and repeat after eight", () => {
    const releases = releaseColours(data);
    expect([...releases.values()].map((r) => [r.name, r.colour])).toEqual([
        ["R1", RELEASE_COLOURS[0]],
        ["R2", RELEASE_COLOURS[1]],
    ]);
    const many = { projects: [{ rows: Array.from({ length: 9 }, (_, i) => item(i + 1, "ready", i + 1, `Release ${i + 1}`)) }] };
    const colours = [...releaseColours(many).values()].map((r) => r.colour);
    expect(colours[8]).toBe(colours[0]);
});

test("a bar takes its colour from the status or the release, or keeps the standard look", () => {
    const releases = releaseColours(data);
    expect(barColour(item(1, "done"), "status", releases)).toBe("var(--ag-s-done)");
    expect(barColour(item(1, "done", 5, "R1"), "release", releases)).toBe(RELEASE_COLOURS[0]);
    expect(barColour(item(3, "ready"), "release", releases)).toBe("");
    expect(barColour(item(1, "done"), "default", releases)).toBe("");
});

test("the legend lists each status, or each release and 'No release' when some bars have none", async () => {
    await makeMockEnv();
    const releases = releaseColours(data);
    expect(colourLegend("status", releases, data).map((e) => e.key)).toEqual(["backlog", "ready", "progress", "review", "done", "canceled"]);
    expect(colourLegend("release", releases, data).map((e) => e.label)).toEqual(["R1", "R2", "No release"]);
    expect(colourLegend("default", releases, data)).toEqual([]);
});

test("a share link carries the id and the page reads it back", () => {
    expect(shareLink("https://odoo.example", 12)).toBe("https://odoo.example/odoo/action-agile_community.agile_roadmap_page_action?roadmap_share=12");
    expect(shareIdFrom({ share_id: 4 }, "")).toBe(4);
    expect(shareIdFrom({}, "?roadmap_share=12&debug=1")).toBe(12);
    expect(shareIdFrom({}, "?roadmap_share=abc")).toBe(null);
    expect(shareIdFrom({}, "")).toBe(null);
});
