import { Component, onMounted, useRef } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

/** The phone twin of drag and keyboard: one list of what can be done to an issue. */
export class AgileRowSheet extends Component {
    static template = "agile_community.RowSheet";
    static components = { Dialog };
    static props = {
        title: String,
        actions: Array,
        onSelect: Function,
        close: Function,
    };

    setup() {
        this.listRef = useRef("list");
        onMounted(() => this.listRef.el?.querySelector("button")?.focus());
    }

    select(action) {
        this.props.close();
        this.props.onSelect(action);
    }
}
