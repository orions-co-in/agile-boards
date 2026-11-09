import { signal } from "@odoo/owl";
import { Component, useProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import {useLayoutEffect} from "@web/owl2/utils";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

// The status category each step button leads to.
const BUTTON_TARGETS = {
    action_agile_mark_ready: "ready",
    action_agile_start: "progress",
    action_agile_send_review: "review",
    action_agile_return: "progress",
    action_agile_complete: "done",
    action_agile_reopen: "progress",
};
const UNMET = "o_ag_step_unmet";

/**
 * Marks the step buttons next to it (Start, Review, Complete...) that the workflow would refuse now:
 * muted, with the reason as tooltip and aria-disabled. They stay clickable, so the server's message
 * is still shown (and announced) when someone presses one.
 */
export class AgileStepReasons extends Component {
    static template = "agile_community.StepReasons";
    props = useProps({ ...standardFieldProps });

    setup() {
        this.rootRef = signal.ref();
        useLayoutEffect(
            () => {
                const scope = this.rootRef()?.closest(".o_kanban_record, .o_form_view");
                if (!scope) {
                    return;
                }
                const reasons = this.props.record.data[this.props.name] || {};
                const marked = [];
                for (const [name, category] of Object.entries(BUTTON_TARGETS)) {
                    const reason = reasons[category];
                    for (const button of scope.querySelectorAll(`button[name="${name}"]`)) {
                        if (reason) {
                            button.classList.add(UNMET);
                            button.setAttribute("aria-disabled", "true");
                            button.dataset.agReason = button.title || "";
                            button.title = reason;
                            marked.push(button);
                        }
                    }
                }
                return () => {
                    for (const button of marked) {
                        button.classList.remove(UNMET);
                        button.removeAttribute("aria-disabled");
                        button.title = button.dataset.agReason || "";
                        delete button.dataset.agReason;
                    }
                };
            },
            () => [JSON.stringify(this.props.record.data[this.props.name] || {})]
        );
    }
}

registry.category("fields").add("agile_step_reasons", {
    component: AgileStepReasons,
    supportedTypes: ["json"],
});
