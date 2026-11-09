import { signal } from "@odoo/owl";
import { Component, onMounted, useProps, t } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";


/** The phone twin of drag and keyboard: one list of what can be done to an issue. */
export class AgileRowSheet extends Component {
    static template = "agile_community.RowSheet";
    static components = { Dialog };
    props = useProps({
        title: t.string(),
        actions: t.array(),
        onSelect: t.function(),
        close: t.function()});

    setup() {
        this.listRef = signal.ref();
        onMounted(() => this.listRef()?.querySelector("button")?.focus());
    }

    select(action) {
        this.props.close();
        this.props.onSelect(action);
    }
}
