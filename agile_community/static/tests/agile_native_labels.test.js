import { describe, expect, test } from "@odoo/hoot";
import { makeMockEnv } from "@web/../tests/web_test_helpers";
import { labelNativeControls } from "@agile_community/components/a11y/agile_native_labels";

describe.current.tags("desktop");

function fixture(html) {
    const root = document.createElement("div");
    root.innerHTML = html;
    return root;
}

test("unnamed fold carets and the panel toggle get names; named ones are left alone", async () => {
    await makeMockEnv();
    const root = fixture(`
        <div class="o_search_panel">
            <div><button class="o_toggle_fold"></button><span class="o_search_panel_label_title"> Sprint </span></div>
            <div><button class="o_toggle_fold" aria-label="Keep me"></button><span class="o_search_panel_label_title">Epic</span></div>
        </div>
        <button><i class="oi oi-panel-right"></i></button>
        <button aria-label="Already named"><i class="oi oi-panel-right"></i></button>`);
    labelNativeControls(root);
    const [first, second] = root.querySelectorAll(".o_toggle_fold");
    expect(first.getAttribute("aria-label")).toBe("Show or hide Sprint");
    expect(second.getAttribute("aria-label")).toBe("Keep me");
    const [panel, named] = root.querySelectorAll("button > i.oi-panel-right");
    expect(panel.parentElement.getAttribute("aria-label")).toBe("Show or hide the filter panel");
    expect(named.parentElement.getAttribute("aria-label")).toBe("Already named");
});
