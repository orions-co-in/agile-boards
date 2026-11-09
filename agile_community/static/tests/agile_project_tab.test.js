import { describe, expect, test } from "@odoo/hoot";
import { readProjectTab, rememberProjectTab } from "@agile_community/form/project_tab_memory";

describe.current.tags("desktop");

test("the project form tab is remembered and read back", () => {
    rememberProjectTab("settings");
    expect(readProjectTab()).toBe("settings");
    rememberProjectTab("releases");
    expect(readProjectTab()).toBe("releases");
});

test("an empty tab name is not stored", () => {
    rememberProjectTab("settings");
    rememberProjectTab(null);
    expect(readProjectTab()).toBe("settings");
});
