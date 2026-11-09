import { Component, onMounted, useRef } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

/** The keyboard twin of drag: a short list of places an issue can go. */
export class AgileMoveToDialog extends Component {
    static template = "agile_community.MoveToDialog";
    static components = { Dialog };
    static props = {
        title: String,
        targets: Array,
        onSelect: Function,
        close: Function,
    };

    setup() {
        this.listRef = useRef("list");
        onMounted(() => this.listRef.el?.querySelector("button")?.focus());
    }

    select(target) {
        this.props.close();
        this.props.onSelect(target);
    }
}
