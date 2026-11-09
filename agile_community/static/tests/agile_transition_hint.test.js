import { describe, expect, test } from "@odoo/hoot";
import { click, edit, queryAll } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { defineModels, fields, models, mountView, onRpc } from "@web/../tests/web_test_helpers";
import "@agile_community/board/agile_transition_hint";

describe.current.tags("desktop");

class ProjectTask extends models.Model {
    _name = "project.task";
    name = fields.Char();
    assignee = fields.Char();
    description = fields.Html();
    agile_transition_hint = fields.Char();
    agile_missing_fields = fields.Char();
    _onChanges = { assignee: () => {} };
    _records = [
        { id: 1, name: "Needs one", agile_transition_hint: "Before In Progress: add an assignee.", agile_missing_fields: "assignee" },
        { id: 2, name: "Ready to go", agile_transition_hint: "", agile_missing_fields: "" },
        { id: 3, name: "No text", agile_transition_hint: "Before Review: add a description.", agile_missing_fields: "description" },
    ];
}

defineMailModels();
defineModels([ProjectTask]);

const ARCH = `<form>
    <field name="agile_missing_fields" invisible="1"/>
    <field name="agile_transition_hint" widget="agile_transition_hint" nolabel="1"/>
    <field name="name"/>
    <field name="assignee"/>
</form>`;

async function mountHint(resId) {
    await mountView({ type: "form", resModel: "project.task", resId, arch: ARCH });
    await animationFrame();
}

test("the line names what the next move needs and marks the empty field in words", async () => {
    await mountHint(1);
    expect(".o_ag_hint").toHaveText(/Before In Progress: add an assignee\./);
    expect(".o_ag_hint_show").toHaveText("Show me");
    expect(".o_field_widget[name=assignee]").toHaveClass("o_ag_needed");
    expect(".o_field_widget[name=assignee]").toHaveAttribute("data-needed", "Needed to move on");
    expect(".o_field_widget[name=name]").not.toHaveClass("o_ag_needed");
});

test("Show me moves focus to the first missing field", async () => {
    await mountHint(1);
    await click(".o_ag_hint_show");
    await animationFrame();
    expect(".o_field_widget[name=assignee] input").toBeFocused();
});

test("Show me puts the caret in an HTML field's text, not on its toolbar (E2E-014)", async () => {
    await mountView({
        type: "form", resModel: "project.task", resId: 3,
        arch: `<form>
            <field name="agile_missing_fields" invisible="1"/>
            <field name="agile_transition_hint" widget="agile_transition_hint" nolabel="1"/>
            <field name="description"/>
        </form>`,
    });
    await animationFrame();
    // An editor puts buttons before its text; Show me must skip them.
    const widget = document.querySelector(".o_field_widget[name=description]");
    const button = document.createElement("button");
    button.textContent = "Insert image";
    widget.prepend(button);
    await click(".o_ag_hint_show");
    await animationFrame();
    expect(document.activeElement.isContentEditable).toBe(true);
    expect(document.activeElement.closest(".o_field_widget").getAttribute("name")).toBe("description");
});

test("nothing to say, nothing shown", async () => {
    await mountHint(2);
    expect(".o_ag_hint").toHaveCount(0);
    expect(queryAll(".o_ag_needed")).toHaveLength(0);
});

test("the line and the marks clear as soon as the record no longer needs anything", async () => {
    onRpc("project.task", "onchange", () => ({
        value: { agile_transition_hint: "", agile_missing_fields: "" },
    }));
    await mountHint(1);
    await click(".o_field_widget[name=assignee] input");
    await edit("Sam");
    await click(".o_field_widget[name=name] input"); // leaving the field sends the change
    await animationFrame();
    await animationFrame();
    expect(".o_ag_hint").toHaveCount(0);
    expect(queryAll(".o_ag_needed")).toHaveLength(0);
});
