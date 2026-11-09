import { describe, expect, test } from "@odoo/hoot";
import { click, edit, press, queryAllTexts } from "@odoo/hoot-dom";
import { animationFrame, advanceTime } from "@odoo/hoot-mock";
import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { defineModels, fields, getService, makeMockEnv, mountWithCleanup, models, onRpc } from "@web/../tests/web_test_helpers";
import { MainComponentsContainer } from "@web/core/main_components_container";
import { AgilePalette } from "@agile_community/palette/agile_palette";
import { buildSections, isPaletteKey, matchTargets, moveIndex } from "@agile_community/palette/palette_helpers";

describe.current.tags("desktop");

class ProjectTask extends models.Model {
    _name = "project.task";
    name = fields.Char();
}
defineMailModels();
defineModels([ProjectTask]);

const press_ = (key, extra = {}) => ({ key, defaultPrevented: false, ctrlKey: false, metaKey: false, altKey: false, shiftKey: false, ...extra });

test("Ctrl+K and Cmd+K open the palette, nothing else does", async () => {
    await makeMockEnv();
    expect(isPaletteKey(press_("k", { ctrlKey: true }))).toBe(true);
    expect(isPaletteKey(press_("K", { metaKey: true }))).toBe(true);
    expect(isPaletteKey(press_("k"))).toBe(false);
    expect(isPaletteKey(press_("k", { ctrlKey: true, shiftKey: true }))).toBe(false);
    expect(isPaletteKey(press_("k", { ctrlKey: true, defaultPrevented: true }))).toBe(false);
    expect(isPaletteKey(press_("j", { ctrlKey: true }))).toBe(false);
});

test("sections keep only what has rows and the arrow keys wrap", async () => {
    await makeMockEnv();
    const { sections, flat } = buildSections({
        issues: [{ id: 1, key: "A-1", name: "One" }],
        issuesTitle: "Issues",
        screens: [],
        actions: [{ key: "shortcuts", label: "Keyboard shortcuts" }],
    });
    expect(sections.map((s) => s.title)).toEqual(["Issues", "Actions"]);
    expect(flat.map((item) => item.type)).toEqual(["issue", "action"]);
    expect(flat.map((item) => item.index)).toEqual([0, 1]);
    expect(moveIndex(0, -1, 3)).toBe(2);
    expect(moveIndex(2, 1, 3)).toBe(0);
    expect(moveIndex(0, 1, 0)).toBe(0);
    expect(matchTargets([{ label: "Backlog" }, { label: "Board" }], "bo").map((t) => t.label)).toEqual(["Board"]);
    expect(matchTargets([{ label: "Backlog" }], "  ").length).toBe(1);
});

test("issues of other projects get their own group after the open project's", async () => {
    await makeMockEnv();
    const issue = (id, project_id) => ({ id, key: `K-${id}`, name: `Issue ${id}`, project: `P${project_id}`, project_id });
    const { sections, flat } = buildSections({
        issues: [issue(1, 7), issue(2, 8), issue(3, 7)],
        issuesTitle: "Issues",
        screens: [],
        actions: [],
        projectId: 7,
    });
    expect(sections.map((s) => s.title)).toEqual(["Issues", "In other projects"]);
    expect(sections[0].items.map((item) => item.issue.id)).toEqual([1, 3]);
    expect(sections[1].items.map((item) => item.issue.id)).toEqual([2]);
    expect(flat.map((item) => item.index)).toEqual([0, 1, 2]);
});

async function mountPalette(onClose = () => {}) {
    await makeMockEnv();
    await mountWithCleanup(MainComponentsContainer);
    // A Dialog needs the dialog service's environment, so open the palette the way the app does.
    getService("dialog").add(AgilePalette, { projectId: 7, entries: ["backlog", "board"] }, { onClose });
    await animationFrame();
    await animationFrame();
}

test("with nothing typed the palette lists recent issues and the screens of the project", async () => {
    onRpc("project.task", "agile_palette_recent", () => [
        { id: 3, key: "SHOP-3", name: "Pay by card", project: "Shop", status: "In Progress" },
    ]);
    await mountPalette();
    expect(".o_ag_palette_heading:first").toHaveText("Recent issues");
    const rows = queryAllTexts(".o_ag_palette_row").map((text) => text.replace(/\s+/g, " ").trim());
    expect(rows).toEqual(["SHOP-3 Pay by card In Progress in Shop", "Backlog", "Board", "Keyboard shortcuts"]);
});

test("typing searches the server and a miss says only that nothing matches", async () => {
    const searched = [];
    onRpc("project.task", "agile_palette_recent", () => []);
    onRpc("project.task", "agile_palette_search", ({ args }) => {
        searched.push(args);
        return [];
    });
    await mountPalette();
    await click(".o_ag_palette_input");
    await edit("SHOP-99");
    await advanceTime(300);
    await animationFrame();
    expect(searched).toEqual([["SHOP-99", 7]]);
    expect(".o_ag_palette_empty").toHaveText('Nothing matches "SHOP-99".');
    expect(".o_ag_palette_row").toHaveCount(0);
});

test("Enter on an issue closes the palette and opens the issue, even right after typing", async () => {
    let closed = 0;
    onRpc("project.task", "agile_palette_recent", () => []);
    onRpc("project.task", "agile_palette_search", () => [
        { id: 9, key: "SHOP-9", name: "Refund page", project: "Shop", status: "Backlog" },
    ]);
    await mountPalette(() => closed++);
    await click(".o_ag_palette_input");
    await edit("shop-9");
    await press("Enter");
    await animationFrame();
    expect(closed).toBe(1);
});
