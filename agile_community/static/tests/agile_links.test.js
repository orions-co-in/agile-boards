import { describe, expect, test } from "@odoo/hoot";
import { click, edit, queryAllTexts } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { defineModels, fields, models, mountView, onRpc } from "@web/../tests/web_test_helpers";
import "@agile_community/links/agile_links";

describe.current.tags("desktop");

class ProjectTask extends models.Model {
    _name = "project.task";
    name = fields.Char();
    agile_related_issue_ids = fields.Many2many({ relation: "project.task" });
    _records = [{ id: 1, name: "Checkout" }, { id: 2, name: "Search" }];
}

defineMailModels();
defineModels([ProjectTask]);

const ARCH = `<form><field name="agile_related_issue_ids" widget="agile_links" nolabel="1"/></form>`;

const item = (kind, id, key, name) => ({
    kind, id, key, name, status: "backlog", status_label: "Backlog", link_id: false, project: "Shop",
});

function panel(overrides = {}) {
    return {
        groups: [
            { kind: "blocked_by", label: "Is blocked by", items: [item("blocked_by", 3, "SHOP-0003", "Mobile app")] },
            { kind: "clones", label: "Clones", items: [item("clones", 2, "SHOP-0002", "Search")] },
        ],
        hidden: 2,
        can_edit: true,
        allow_blocking: true,
        ...overrides,
    };
}

async function mountLinks() {
    await mountView({ type: "form", resModel: "project.task", resId: 1, arch: ARCH });
    await animationFrame();
}

test("links are grouped by their sentence and hidden ones are only counted", async () => {
    onRpc("project.task", "agile_links_data", () => panel());
    await mountLinks();
    expect(queryAllTexts(".o_ag_links_group")).toEqual(["Is blocked by", "Clones"]);
    expect(queryAllTexts(".o_ag_links_key")).toEqual(["SHOP-0003", "SHOP-0002"]);
    expect(".o_ag_links_hidden").toHaveText("2 more links you cannot see.");
});

test("a person who cannot edit reads the links and is told why there is no Add link", async () => {
    onRpc("project.task", "agile_links_data", () => panel({ can_edit: false, hidden: 0 }));
    await mountLinks();
    expect(".o_ag_links_header button").toHaveCount(0);
    expect(".o_ag_links_remove").toHaveCount(0);
    expect(".o_ag_links").toHaveText(/You can read links but not change them/);
});

test("Add link searches by key, adds with Enter and announces it", async () => {
    let added = null;
    onRpc("project.task", "agile_links_data", () => panel({ groups: [], hidden: 0 }));
    onRpc("project.task", "search_read", () => [{ id: 2, issue_key: "SHOP-0002", name: "Search", project_id: [1, "Shop"] }]);
    onRpc("project.task", "agile_add_link", ({ args }) => {
        added = args;
        return panel({ hidden: 0 });
    });
    await mountLinks();
    expect(".o_ag_links").toHaveText(/No links yet/);
    await click(".o_ag_links_header button");
    await animationFrame();
    expect(".o_ag_links_box input").toBeFocused();
    await edit("SHOP-0002");
    await animationFrame();
    await animationFrame();
    await click(".o_ag_links_result");
    await animationFrame();
    expect(added).toEqual([[1], "blocks", 2]);
    expect(".o_ag_links [role=status]").toHaveText("Link added: Blocks SHOP-0002");
    expect(".o_ag_links_header button").toBeFocused();
});

test("a refused link shows the server's sentence and keeps the box open", async () => {
    onRpc("project.task", "agile_links_data", () => panel({ groups: [], hidden: 0 }));
    onRpc("project.task", "search_read", () => [{ id: 2, issue_key: "SHOP-0002", name: "Search", project_id: [1, "Shop"] }]);
    onRpc("project.task", "agile_add_link", () => {
        throw new Error("fail");
    });
    await mountLinks();
    await click(".o_ag_links_header button");
    await animationFrame();
    await edit("Search");
    await animationFrame();
    await animationFrame();
    await click(".o_ag_links_result");
    await animationFrame();
    expect(".o_ag_links_problem").toHaveCount(1);
    expect(".o_ag_links_box").toHaveCount(1);
});

test("removing a link asks the server and shows the fresh list", async () => {
    let removed = null;
    onRpc("project.task", "agile_links_data", () => panel());
    onRpc("project.task", "agile_remove_link", ({ args }) => {
        removed = args;
        return panel({ groups: [], hidden: 0 });
    });
    await mountLinks();
    await click(".o_ag_links_remove");
    await animationFrame();
    expect(removed).toEqual([[1], "blocked_by", 3]);
    expect(".o_ag_links_row").toHaveCount(0);
});

test("without the blocking setting the type list has no Blocks entries", async () => {
    onRpc("project.task", "agile_links_data", () => panel({ allow_blocking: false }));
    await mountLinks();
    await click(".o_ag_links_header button");
    await animationFrame();
    expect(queryAllTexts(".o_ag_links select option")).toEqual([
        "Clones", "Is cloned by", "Duplicates", "Is duplicated by", "Relates to",
    ]);
});
