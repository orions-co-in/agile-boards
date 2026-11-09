import { describe, expect, test } from "@odoo/hoot";
import { click, edit, press, queryAllTexts } from "@odoo/hoot-dom";
import { animationFrame, advanceTime } from "@odoo/hoot-mock";
import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import {
    defineModels,
    fields,
    makeMockEnv,
    models,
    mountView,
    onRpc,
} from "@web/../tests/web_test_helpers";
import { applySuggestion, countText, quoteValue, rowsToQuery } from "@agile_community/filter/agile_query_field";

describe.current.tags("desktop");

class AgileFilter extends models.Model {
    _name = "agile.filter";
    name = fields.Char();
    project_id = fields.Many2one({ relation: "project.project" });
    query = fields.Char();
    _records = [{ id: 1, name: "F", project_id: 7, query: "" }];
}

class ProjectProject extends models.Model {
    _name = "project.project";
    name = fields.Char();
    _records = [{ id: 7, name: "P" }];
}

defineMailModels();
defineModels([AgileFilter, ProjectProject]);

const OPTIONS = [
    {
        field: "status",
        label: "Status",
        kind: "status",
        ops: [{ op: "=", label: "is" }, { op: "!=", label: "is not" }, { op: "IS EMPTY", label: "is empty" }],
        values: ["Backlog", "In Progress"],
    },
    {
        field: "due",
        label: "Due date",
        kind: "date",
        ops: [{ op: "<", label: "is before" }],
        values: null,
    },
];

const SUGGEST = { start: 0, end: 3, items: [{ label: "status", insert: "status", hint: "where it is" }] };

test("accepting a suggestion replaces the typed fragment and moves on", async () => {
    await makeMockEnv();
    const done = applySuggestion("sta", { start: 0, end: 3 }, { insert: "status" });
    expect(done).toEqual({ text: "status ", cursor: 7 });
    expect(applySuggestion("type = B", { start: 7, end: 8 }, { insert: "Bug" }).text).toBe("type = Bug ");
    // A bracket is not followed by a space.
    expect(applySuggestion("assignee IN ", { start: 12, end: 12 }, { insert: "(" }).text).toBe(
        "assignee IN ("
    );
    expect(countText(1)).toBe("1 issue matches");
    expect(countText(12)).toBe("12 issues match");
});

test("the bar shows suggestions, the count and the meaning, or the error", async () => {
    onRpc("agile.filter", "agile_query_options", () => OPTIONS);
    onRpc("agile.filter", "agile_query_assist", ({ args }) => {
        const text = args[1];
        if (text === "statu = Done") {
            return {
                ok: false,
                error: { message: "Unknown field 'statu'. Did you mean 'status'?", start: 0, end: 5 },
                words: "",
                count: null,
                suggest: SUGGEST,
            };
        }
        return {
            ok: !!text,
            rows: null,
            error: null,
            words: text ? "Status is Done" : "",
            count: text ? 12 : null,
            suggest: SUGGEST,
        };
    });
    await mountView({
        type: "form",
        resModel: "agile.filter",
        resId: 1,
        arch: `<form><field name="project_id" invisible="1"/><field name="query" widget="agile_query"/></form>`,
    });
    await animationFrame();
    expect(".o_agile_query_example").toHaveCount(1);
    await click(".o_agile_query_mode button:contains(Advanced)");
    await animationFrame();
    expect(".o_agile_query_bar_hidden").toHaveCount(0);
    await click(".o_agile_query_input");
    await edit("status = Done");
    await advanceTime(400);
    await animationFrame();
    expect(".o_agile_query_count").toHaveText("12 issues match");
    expect(".o_agile_query_words").toHaveText("Status is Done");
    expect(".o_agile_query_list [role=option]").toHaveCount(1);
    expect(queryAllTexts(".o_agile_query_word")).toEqual(["status"]);
    await press("Escape");
    await animationFrame();
    expect(".o_agile_query_list").toHaveCount(0);
    await edit("statu = Done");
    await advanceTime(400);
    await animationFrame();
    expect(".o_agile_query_count").toHaveText("Unknown field 'statu'. Did you mean 'status'?");
    expect(".o_agile_query_input").toHaveAttribute("aria-invalid", "true");
});

test("rows become query text and values are quoted when they need it", async () => {
    await makeMockEnv();
    expect(quoteValue("Bug")).toBe("Bug");
    expect(quoteValue("In Progress")).toBe('"In Progress"');
    expect(quoteValue("and")).toBe('"and"');
    expect(quoteValue('say "hi"')).toBe('"say \\"hi\\""');
    const rows = [
        { field: "status", op: "=", value: "In Progress" },
        { field: "due", op: "<", value: "" },
        { field: "assignee", op: "IS EMPTY", value: "" },
    ];
    // A row still waiting for its value is left out.
    expect(rowsToQuery(rows, false)).toBe('status = "In Progress" AND assignee IS EMPTY');
    expect(rowsToQuery(rows, true)).toBe('status = "In Progress" OR assignee IS EMPTY');
});

test("Basic rows edit the query, and a query Basic cannot show switches to Advanced", async () => {
    onRpc("agile.filter", "agile_query_options", () => OPTIONS);
    onRpc("agile.filter", "agile_query_assist", ({ args }) => {
        const text = args[1];
        const rows = text.startsWith("status")
            ? { match_any: false, rows: [{ field: "status", op: "=", value: "Backlog" }] }
            : null;
        return {
            ok: true,
            rows,
            error: null,
            words: "",
            count: 3,
            suggest: { start: 0, end: 0, items: [] },
        };
    });
    AgileFilter._records[0].query = "status = Backlog";
    await mountView({
        type: "form",
        resModel: "agile.filter",
        resId: 1,
        arch: `<form><field name="project_id" invisible="1"/><field name="query" widget="agile_query"/></form>`,
    });
    await advanceTime(400);
    await animationFrame();
    expect(".o_agile_query_row").toHaveCount(1);
    expect(".o_agile_query_row select:nth-of-type(3)").toHaveValue("Backlog");
    await click(".o_agile_query_chip:contains(Status)");
    await animationFrame();
    expect(".o_agile_query_row").toHaveCount(2);
    expect(".o_agile_query_input").toHaveValue('status = Backlog AND status = Backlog');
    await click(".o_agile_query_remove");
    await animationFrame();
    expect(".o_agile_query_row").toHaveCount(1);
    expect(".o_agile_query_input").toHaveValue("status = Backlog");
    // Typing a query that uses brackets cannot be shown as rows.
    await click(".o_agile_query_mode button:contains(Advanced)");
    await animationFrame();
    expect(".o_agile_query_mode button.active").toHaveText("Advanced");
    expect(".o_agile_query_bar_hidden").toHaveCount(0);
    await click(".o_agile_query_input");
    await animationFrame();
    expect(".o_agile_query_input").toBeFocused();
    await edit("(status = Backlog)");
    await advanceTime(400);
    await animationFrame();
    expect(".o_agile_query_note").toHaveCount(1);
    expect(".o_agile_query_mode button:contains(Basic)").toHaveAttribute("disabled");
});
