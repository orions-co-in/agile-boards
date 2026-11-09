import { Component, useProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/**
 * One button for each workflow move the standard buttons do not cover, such as
 * "Send to QA" (NU-08). The server decides which moves the user may take.
 */
export class AgileCustomMoves extends Component {
    static template = "agile_community.CustomMoves";
    props = useProps({ ...standardFieldProps });

    setup() {
        this.orm = useService("orm");
    }

    get moves() {
        try {
            return JSON.parse(this.props.record.data[this.props.name] || "[]");
        } catch {
            return [];
        }
    }

    async take(move) {
        const record = this.props.record;
        const save = await record.save?.();
        if (save === false) {
            return;
        }
        await this.orm.call("project.task", "action_agile_custom_move", [[record.resId], move.id]);
        await record.load();
    }
}

registry.category("fields").add("agile_custom_moves", {
    component: AgileCustomMoves,
    supportedTypes: ["char"],
});
