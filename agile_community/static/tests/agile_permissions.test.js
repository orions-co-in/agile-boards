import { describe, expect, test } from "@odoo/hoot";
import { click, queryAllTexts, waitFor } from "@odoo/hoot-dom";
import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { WebClient } from "@web/webclient/webclient";
import { defineModels, getService, makeTestApp, models, mountWithCleanup, onRpc } from "@web/../tests/web_test_helpers";
import { switchQuestion } from "@agile_community/permissions/agile_permissions";

describe.current.tags("desktop");

class AgilePermissionsModel extends models.Model {
    _name = "agile.permissions";
}

defineMailModels();
defineModels([AgilePermissionsModel]);

const SCHEMES = [
    { key: "standard", label: "Standard", sentence: "Today's behaviour." },
    { key: "open", label: "Open", sentence: "Contributors can also complete issues." },
    { key: "custom", label: "Custom", sentence: "Your team picks." },
];
const data = (scheme) => ({
    project: { id: 1, name: "Demo Shop" },
    scheme,
    schemes: SCHEMES,
    matrix: {
        standard: [{ action: "Complete an issue", roles: ["Project Manager", "Reviewer"] }],
        open: [{ action: "Complete an issue", roles: ["Project Manager", "Contributor", "Reviewer"] }],
        custom: [{ key: "complete", action: "Complete an issue", editable: true, grants: ["reviewer"], roles: ["Project Manager", "Reviewer"] }],
    },
    can_change: true,
});

test("the switch question names the project, the scheme and that it applies now", async () => {
    await makeTestApp();
    expect(String(switchQuestion("Demo Shop", SCHEMES[1]))).toBe(
        "Switch Demo Shop to Open? Contributors can also complete issues. This takes effect now for everyone."
    );
});

test.timeout(20000);
test("the page shows the scheme cards and the table, and switching asks first", async () => {
    let scheme = "standard";
    const calls = [];
    onRpc("agile.permissions", "permissions_data", () => data(scheme));
    onRpc("agile.permissions", "set_scheme", ({ args }) => {
        calls.push(args[1]);
        scheme = args[1];
        return data(scheme);
    });
    await mountWithCleanup(WebClient);
    await getService("action").doAction({ type: "ir.actions.client", tag: "agile_community.permissions", params: { project_id: 1 } });
    await waitFor(".o_ag_perm_table");
    expect(".o_ag_perm_title").toHaveText("Permissions in Demo Shop");
    expect(queryAllTexts(".o_ag_perm_card b")).toEqual(["Standard", "Open", "Custom"]);
    expect(queryAllTexts(".o_ag_perm_table tbody td")).toEqual(["Project Manager, Reviewer"]);
    await click(".o_ag_perm_card:nth-child(2) input");
    await waitFor(".modal");
    expect(calls).toEqual([]);
    await click(".modal-footer .btn-primary");
    await waitFor(".o_ag_perm_card_on:contains(Open)");
    expect(calls).toEqual(["open"]);
    expect(queryAllTexts(".o_ag_perm_table tbody td")).toEqual(["Project Manager, Contributor, Reviewer"]);
});

test.timeout(20000);
test("on Custom the Contributor and Reviewer columns can be ticked and saved", async () => {
    const saved = [];
    onRpc("agile.permissions", "permissions_data", () => data("custom"));
    onRpc("agile.permissions", "set_custom", ({ args }) => {
        saved.push(args[1]);
        return data("custom");
    });
    await mountWithCleanup(WebClient);
    await getService("action").doAction({ type: "ir.actions.client", tag: "agile_community.permissions", params: { project_id: 1 } });
    await waitFor(".o_ag_perm_table input[type=checkbox]");
    expect(queryAllTexts(".o_ag_perm_table thead th")).toEqual(["Action", "Project Manager", "Contributor", "Reviewer"]);
    expect(".o_ag_perm_save button").toHaveProperty("disabled", true);
    await click(".o_ag_perm_table input[type=checkbox]:first");
    await waitFor(".o_ag_perm_save button:not(:disabled)");
    await click(".o_ag_perm_save button");
    await waitFor(".o_ag_perm_save button:disabled");
    expect(saved).toEqual([{ complete: ["reviewer", "contributor"] }]);
});
