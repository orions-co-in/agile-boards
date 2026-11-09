import { Component, onMounted, useRef, useSubEnv } from "@odoo/owl";
import { CallbackRecorder } from "@web/search/action_hook";
import { useService } from "@web/core/utils/hooks";
import { View, getDefaultConfig } from "@web/views/view";

/**
 * The side drawer of the board: the compact issue form next to the columns.
 * Closing it saves what was changed; a record that cannot be saved keeps it open.
 */
export class AgileCardDrawer extends Component {
    static template = "agile_community.CardDrawer";
    static components = { View };
    static props = {
        resId: Number,
        viewId: Number,
        context: { type: Object, optional: true },
        register: Function,
        onClose: Function,
        onExpand: Function,
    };

    setup() {
        // The embedded form must not rename the board's breadcrumb.
        useSubEnv({ config: getDefaultConfig() });
        // Opening the drawer counts as viewing the issue, for the command palette's recent list.
        this.orm = useService("orm");
        this.orm.silent.call("project.task", "agile_palette_visit", [[this.props.resId]]).catch(() => {});
        this.rootRef = useRef("root");
        this.beforeLeave = new CallbackRecorder();
        this.viewProps = {
            type: "form",
            resModel: "project.task",
            resId: this.props.resId,
            viewId: this.props.viewId,
            context: { ...(this.props.context || {}), form_view_ref: undefined },
            display: { controlPanel: false },
            preventCreate: true,
            __beforeLeave__: this.beforeLeave,
        };
        this.props.register(() => this.leave());
        onMounted(() => this.rootRef.el?.focus());
    }

    /** Save pending changes; false when the record cannot be saved yet. */
    async leave() {
        const results = await Promise.all(this.beforeLeave.callbacks.map((callback) => callback()));
        return !results.includes(false);
    }

    async close() {
        if (await this.leave()) {
            this.props.onClose();
        }
    }

    async expand() {
        if (await this.leave()) {
            this.props.onExpand(this.props.resId);
        }
    }

    onKeydown(ev) {
        if (ev.key !== "Escape" || ev.defaultPrevented) {
            return;
        }
        // Escape closes menus and pickers first; the drawer only when nothing else is open.
        if (document.querySelector(".o-dropdown--menu, .o-autocomplete--dropdown-menu, .modal.show")) {
            return;
        }
        ev.stopPropagation();
        this.close();
    }
}
