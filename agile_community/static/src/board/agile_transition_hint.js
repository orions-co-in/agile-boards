import { Component, useEffect, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

const NEEDED = "o_ag_needed";

/**
 * "Before Review: add an assignee and a description." above the issue form, with the
 * empty fields marked in words and a link that moves focus to the first one.
 * The record's computed hint changes as fields are filled, so the line clears at once.
 */
export class AgileTransitionHint extends Component {
    static template = "agile_community.TransitionHint";
    static props = { ...standardFieldProps };

    setup() {
        this.rootRef = useRef("root");
        useEffect(
            () => {
                const form = this.rootRef.el?.closest(".o_form_view");
                if (!form) {
                    return;
                }
                const marked = this.missing.map((name) => form.querySelector(`.o_field_widget[name="${name}"]`));
                for (const el of marked.filter(Boolean)) {
                    el.classList.add(NEEDED);
                    el.dataset.needed = _t("Needed to move on");
                }
                return () => {
                    for (const el of marked.filter(Boolean)) {
                        el.classList.remove(NEEDED);
                        delete el.dataset.needed;
                    }
                };
            },
            () => [this.props.record.data.agile_missing_fields]
        );
    }

    get hint() {
        return this.props.record.data[this.props.name] || "";
    }

    get missing() {
        return (this.props.record.data.agile_missing_fields || "").split(",").filter(Boolean);
    }

    showMe(ev) {
        ev.preventDefault();
        const form = this.rootRef.el.closest(".o_form_view");
        for (const name of this.missing) {
            const target = form?.querySelector(`.o_field_widget[name="${name}"]`);
            const focusable = target?.matches("input, textarea, [contenteditable]")
                ? target
                : // The text first: an HTML field's editor has toolbar buttons (Insert image) before its text (E2E-014).
                  target?.querySelector('[contenteditable="true"], .note-editable, input:not([type=hidden]), textarea') ||
                  target?.querySelector("button");
            if (focusable) {
                focusable.scrollIntoView?.({ block: "center" });
                focusable.focus();
                return;
            }
        }
    }
}

registry.category("fields").add("agile_transition_hint", {
    component: AgileTransitionHint,
    supportedTypes: ["char"],
});
