import { describe, expect, test } from "@odoo/hoot";
import { pushState } from "@agile_community/notifications/push_helpers";

describe.current.tags("desktop");

const base = { canNotify: true, isIOS: false, standalone: false, permission: "prompt", inboxOk: true };

describe("phone push wording", () => {
    test("off until the person allows it, then the button shows", () => {
        expect(pushState(base).kind).toBe("off");
    });

    test("an iPhone browser tab is told to install the app first", () => {
        const state = pushState({ ...base, isIOS: true });
        expect(state.kind).toBe("needs_install");
        expect(state.text).toInclude("Home Screen");
    });

    test("an installed iPhone app can turn it on", () => {
        expect(pushState({ ...base, isIOS: true, standalone: true }).kind).toBe("off");
    });

    test("a browser without notifications says so", () => {
        expect(pushState({ ...base, canNotify: false }).kind).toBe("unsupported");
    });

    test("a blocked site points to the browser settings", () => {
        const state = pushState({ ...base, permission: "denied" });
        expect(state.kind).toBe("blocked");
        expect(state.text).toInclude("browser settings");
    });

    test("allowed with In Odoo is on", () => {
        expect(pushState({ ...base, permission: "granted" }).kind).toBe("on");
    });

    test("allowed with By Emails warns that status messages will not arrive", () => {
        const state = pushState({ ...base, permission: "granted", inboxOk: false });
        expect(state.kind).toBe("on_but_email");
        expect(state.text).toInclude("By Emails");
    });
});
