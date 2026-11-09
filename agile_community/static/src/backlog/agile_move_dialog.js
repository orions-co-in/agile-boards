import { signal } from "@odoo/owl";
import { Component, onMounted, useProps, t } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";


/** The keyboard twin of drag: a short list of places an issue can go. */
export class AgileMoveToDialog extends Component {
    static template = "agile_community.MoveToDialog";
    static components = { Dialog };
    props = useProps({
        title: t.string(),
        targets: t.array(),
        onSelect: t.function(),
        close: t.function()});

    setup() {
        this.listRef = signal.ref();
        onMounted(() => this.listRef()?.querySelector("button")?.focus());
    }

    select(target) {
        this.props.close();
        this.props.onSelect(target);
    }
}
