import { describe, expect, test } from "@odoo/hoot";
import { click, queryAllTexts } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { defineModels, fields, models, mountView, onRpc } from "@web/../tests/web_test_helpers";
import "@agile_community/history/agile_history";

describe.current.tags("desktop");

class ProjectTask extends models.Model {
    _name = "project.task";
    name = fields.Char();
    message_ids = fields.One2many({ relation: "mail.message", relation_field: "res_id" });
    _records = [{ id: 1, name: "Checkout" }];
}

defineMailModels();
defineModels([ProjectTask]);

const ARCH = `<form><field name="message_ids" widget="agile_history" nolabel="1"/></form>`;

const entry = (key, kind, extra = {}) => ({
    key, kind, date: "2026-11-02 09:00:00", author: "Ana", text: "", changes: [], note: false, ...extra,
});

function feed(overrides = {}) {
    return {
        worklog_available: true,
        entries: [
            entry("w1", "worklog", { hours: 1.5, work_date: "2026-11-02", text: "Pairing" }),
            entry("m2", "history", { changes: [{ field: "Stage", old: "Backlog", new: "To Do" }] }),
            entry("m1", "comment", { text: "Looks good" }),
        ],
        ...overrides,
    };
}

async function mountHistory() {
    await mountView({ type: "form", resModel: "project.task", resId: 1, arch: ARCH });
    await animationFrame();
}

test("tabs show a count each and filter the one feed", async () => {
    onRpc("project.task", "agile_history_feed", () => feed());
    await mountHistory();
    expect(queryAllTexts(".o_ag_history_tab")).toEqual(["All 3", "Comments 1", "History 1", "Work log 1"]);
    expect(".o_ag_history_row").toHaveCount(3);
    await click(".o_ag_history_tab[data-tab=comment]");
    await animationFrame();
    expect(queryAllTexts(".o_ag_history_body")).toEqual(["Looks good"]);
    await click(".o_ag_history_tab[data-tab=history]");
    await animationFrame();
    expect(".o_ag_history_changes").toHaveText(/Stage:\s*Backlog\s*→\s*To Do/);
});

test("the work log tab lists the hours that were logged", async () => {
    onRpc("project.task", "agile_history_feed", () => feed());
    await mountHistory();
    await click(".o_ag_history_tab[data-tab=worklog]");
    await animationFrame();
    expect(".o_ag_history_body").toHaveText(/1\.5 h on 2026-11-02: Pairing/);
});

test("without the Timesheets app the work log tab explains why it is empty", async () => {
    onRpc("project.task", "agile_history_feed", () => feed({ worklog_available: false, entries: [] }));
    await mountHistory();
    await click(".o_ag_history_tab[data-tab=worklog]");
    await animationFrame();
    expect(".o_ag_history_note").toHaveText(/Work log needs the Timesheets app/);
});

test("arrow keys move between tabs and the selected tab is announced", async () => {
    onRpc("project.task", "agile_history_feed", () => feed());
    await mountHistory();
    expect(".o_ag_history_tab[data-tab=all]").toHaveAttribute("aria-selected", "true");
    await click(".o_ag_history_tab[data-tab=all]");
    await animationFrame();
    const tab = document.querySelector(".o_ag_history_tab[data-tab=all]");
    tab.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
    await animationFrame();
    expect(".o_ag_history_tab[data-tab=comment]").toHaveAttribute("aria-selected", "true");
});
