import { describe, expect, test } from "@odoo/hoot";
import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";
import { queryOne } from "@odoo/hoot-dom";
import {
    AgileAvatar,
    AgileChip,
    AgileLozenge,
    AgileTypeDot,
} from "@agile_community/components/kit/agile_kit";

describe.current.tags("desktop");

defineMailModels();

test("lozenge shows label with a status icon and falls back to backlog", async () => {
    await mountWithCleanup(AgileLozenge, { props: { label: "Done", category: "done" } });
    expect(".o_ag_lozenge").toHaveClass("o_ag_s_done");
    expect(".o_ag_lozenge [data-icon='check']").toHaveCount(1);
    await mountWithCleanup(AgileLozenge, { props: { label: "?", category: "bogus" } });
    expect(".o_ag_lozenge.o_ag_s_backlog").toHaveCount(1);
});

test("avatar builds initials and exposes an accessible label", async () => {
    await mountWithCleanup(AgileAvatar, { props: { name: "Ada Lovelace Byron" } });
    expect(".o_ag_avatar").toHaveText("AB");
    expect(".o_ag_avatar").toHaveAttribute("aria-label", "Ada Lovelace Byron");
});

test("avatar without a name reads as unassigned", async () => {
    await mountWithCleanup(AgileAvatar, { props: {} });
    expect(".o_ag_avatar").toHaveText("?");
    expect(".o_ag_avatar").toHaveAttribute("aria-label", "Unassigned");
});

test("chip renders a pressable button only when clickable", async () => {
    let clicks = 0;
    await mountWithCleanup(AgileChip, {
        props: { label: "Mine", active: true, onClick: () => clicks++ },
    });
    expect("button.o_ag_chip").toHaveAttribute("aria-pressed", "true");
    queryOne("button.o_ag_chip").click();
    expect(clicks).toBe(1);
});

test("type dot falls back to task for unknown types", async () => {
    await mountWithCleanup(AgileTypeDot, { props: { type: "weird" } });
    expect(".o_ag_type_dot").toHaveClass("o_ag_t_task");
});
