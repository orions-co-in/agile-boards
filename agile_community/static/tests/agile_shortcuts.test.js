import { describe, expect, test } from "@odoo/hoot";
import { makeMockEnv } from "@web/../tests/web_test_helpers";
import { SHORTCUTS, isTypingTarget, shortcutFor } from "@agile_community/shortcuts/shortcut_helpers";

describe.current.tags("desktop");

const press = (key, target = document.body, extra = {}) => ({
    key, target, defaultPrevented: false, repeat: false, ctrlKey: false, metaKey: false, altKey: false, shiftKey: false, ...extra,
});

test("c, /, m and ? ask for their shortcut", async () => {
    await makeMockEnv();
    expect(shortcutFor(press("c"))).toBe("create");
    expect(shortcutFor(press("/"))).toBe("search");
    expect(shortcutFor(press("m"))).toBe("move");
    expect(shortcutFor(press("?", document.body, { shiftKey: true }))).toBe("help");
    expect(shortcutFor(press("x"))).toBe(null);
});

test("nothing happens while typing, with a modifier, on a held key or an already handled press", async () => {
    await makeMockEnv();
    for (const tag of ["input", "textarea", "select"]) {
        expect(shortcutFor(press("c", document.createElement(tag)))).toBe(null);
    }
    const editable = document.createElement("div");
    editable.setAttribute("contenteditable", "true");
    expect(isTypingTarget(editable)).toBe(true);
    expect(isTypingTarget(document.createElement("button"))).toBe(false);
    expect(shortcutFor(press("c", document.body, { ctrlKey: true }))).toBe(null);
    expect(shortcutFor(press("c", document.body, { metaKey: true }))).toBe(null);
    expect(shortcutFor(press("m", document.body, { altKey: true }))).toBe(null);
    expect(shortcutFor(press("c", document.body, { repeat: true }))).toBe(null);
    expect(shortcutFor(press("c", document.body, { defaultPrevented: true }))).toBe(null);
    expect(shortcutFor(press("C", document.body, { shiftKey: true }))).toBe(null);
});

test("the help lists every shortcut with what it does and where", async () => {
    await makeMockEnv();
    expect(SHORTCUTS.map((item) => item.keys)).toEqual(["c", "/", "m", "Ctrl + K", "?", "Alt + Up, Alt + Down"]);
    expect(SHORTCUTS.every((item) => String(item.label).length && String(item.where).length)).toBe(true);
});
