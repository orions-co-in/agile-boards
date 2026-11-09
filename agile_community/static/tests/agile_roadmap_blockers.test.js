import { describe, expect, test } from "@odoo/hoot";
import { click, edit, press, queryAllTexts, waitFor } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { MainComponentsContainer } from "@web/core/main_components_container";
import { WebClient } from "@web/webclient/webclient";
import { defineModels, getService, models, mountWithCleanup, onRpc } from "@web/../tests/web_test_helpers";
import "@agile_community/roadmap/agile_roadmap";

describe.current.tags("desktop");

class AgileRoadmapModel extends models.Model {
    _name = "agile.roadmap";
}

defineMailModels();
defineModels([AgileRoadmapModel]);

const blocker = (id, key, extra = {}) => ({
    id, key, name: `Issue ${key}`, project: "P", status: "progress", end: "2026-10-20", late: false,
    sentence: `Blocked by ${key}, which ends 20 Oct.`, ...extra,
});

async function mountRoadmap({ blockers = [blocker(2, "P-2")], canEdit = true } = {}) {
    const calls = [];
    onRpc("agile.roadmap", "roadmap_projects", () => [{ id: 1, name: "P" }]);
    onRpc("agile.roadmap", "roadmap_data", () => ({
        today: "2026-10-10", multi: false, sprints: [], releases: [], dependencies: [], unscheduled: 0,
        projects: [{ id: 1, name: "P", rows: [{
            kind: "epic", id: 10, key: "P-10", name: "Checkout", start: "2026-10-05", end: "2026-10-25",
            done: 0, total: 0, late: false, circular: false, children: [],
        }] }],
    }));
    let current = blockers;
    onRpc("agile.roadmap", "blockers", () => ({ id: 10, key: "P-10", name: "Checkout", can_edit: canEdit, blockers: current, hidden: 0 }));
    onRpc("agile.roadmap", "search_blockers", ({ args }) => {
        calls.push(["search", args[1]]);
        return args[1] === "loop"
            ? [{ id: 99, key: "P-99", name: "Issue P-99", project: "P" }]
            : [{ id: 3, key: "P-3", name: "Issue P-3", project: "P" }];
    });
    onRpc("agile.roadmap", "add_blocker", ({ args }) => {
        calls.push(["add", args[1]]);
        if (args[1] === 99) {
            throw new Error("P-99 already depends on this issue, so it cannot also block it.");
        }
        current = [...current, blocker(args[1], `P-${args[1]}`)];
        return { id: 10, key: "P-10", name: "Checkout", can_edit: canEdit, blockers: current, hidden: 0 };
    });
    onRpc("agile.roadmap", "remove_blocker", ({ args }) => {
        calls.push(["remove", args[1]]);
        current = current.filter((b) => b.id !== args[1]);
        return { id: 10, key: "P-10", name: "Checkout", can_edit: canEdit, blockers: current, hidden: 0 };
    });
    await mountWithCleanup(WebClient);
    await getService("action").doAction({ type: "ir.actions.client", tag: "agile_community.roadmap", params: { project_ids: [1] } });
    await waitFor(".o_ag_rm_blockers");
    await click(".o_ag_rm_blockers");
    await waitFor(".o_ag_rm_panel .o_ag_rm_blocker");
    return calls;
}

test("the panel lists the blockers in words and Remove offers Undo", async () => {
    const calls = await mountRoadmap();
    expect(queryAllTexts(".o_ag_rm_blocker_text")).toEqual(["Blocked by P-2, which ends 20 Oct."]);
    await click(".o_ag_rm_blocker_remove");
    await waitFor(".o_ag_rm_undo");
    expect(calls).toEqual([["remove", 2]]);
    expect(".o_ag_rm_panel_notice").toHaveText(/Removed P-2\./);
    expect(".o_ag_rm_blocker").toHaveCount(0);
    await click(".o_ag_rm_undo");
    await waitFor(".o_ag_rm_blocker");
    expect(calls.at(-1)).toEqual(["add", 2]);
});

test("searching offers issues and choosing one adds it", async () => {
    const calls = await mountRoadmap();
    await click(".o_ag_rm_add_input");
    await edit("P-3");
    await waitFor(".o_ag_rm_result");
    expect(calls.at(-1)).toEqual(["search", "P-3"]);
    await click(".o_ag_rm_result");
    await waitFor(".o_ag_rm_blocker:nth-child(2)");
    expect(calls.at(-1)).toEqual(["add", 3]);
    expect(".o_ag_rm_panel_notice").toHaveText(/Added P-3 as a blocker\./);
});

// Mounting the whole web client is slow on a busy database, so these get a longer limit.
test.timeout(20000);
test("a refusal shows the server's sentence and keeps the list as it was", async () => {
    await mountRoadmap();
    await click(".o_ag_rm_add_input");
    await edit("loop");
    await waitFor(".o_ag_rm_result");
    await click(".o_ag_rm_result");
    await waitFor(".o_ag_rm_panel_notice:contains(cannot also block it)");
    expect(".o_ag_rm_panel_notice").toHaveText("P-99 already depends on this issue, so it cannot also block it.");
    expect(".o_ag_rm_blocker").toHaveCount(1);
});

// Mounting the whole web client is slow on a busy database, so these get a longer limit.
test.timeout(20000);
test("a person who cannot edit sees the list without Remove or Add", async () => {
    await mountRoadmap({ canEdit: false });
    expect(".o_ag_rm_blocker_remove").toHaveCount(0);
    expect(".o_ag_rm_add_input").toHaveCount(0);
    expect(".o_ag_rm_panel").toHaveText(/Only Agile managers and contributors can change blockers\./);
});

// Mounting the whole web client is slow on a busy database, so these get a longer limit.
test.timeout(20000);
test("Escape closes the panel", async () => {
    await mountRoadmap();
    await click(".o_ag_rm_add_input");
    await press("Escape");
    await animationFrame();
    expect(".o_ag_rm_panel").toHaveCount(0);
});
