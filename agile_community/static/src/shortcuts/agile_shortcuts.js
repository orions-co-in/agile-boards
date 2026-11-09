import { Component, onMounted, onWillUnmount, useProps, t } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/core/dialog/dialog";
import { SHORTCUTS, shortcutFor } from "./shortcut_helpers";

/** The list of shortcuts, opened by "?" and by the Shortcuts link in the sidebar. */
export class AgileShortcutHelp extends Component {
    static template = "agile_community.ShortcutHelp";
    static components = { Dialog };
    props = useProps({ close: t.function()});

    setup() {
        this.shortcuts = SHORTCUTS;
    }
}

export function openShortcutHelp(dialog) {
    dialog.add(AgileShortcutHelp);
}

/**
 * Plain-key shortcuts on the project screens: c creates, / searches, m moves, ? lists them.
 * They only act on screens that show the project sidebar, and never while someone is typing.
 */
export class AgileShortcuts extends Component {
    static template = "agile_community.Shortcuts";
    props = useProps({});

    setup() {
        this.dialog = useService("dialog");
        this.onKeydown = this.onKeydown.bind(this);
        onMounted(() => document.addEventListener("keydown", this.onKeydown));
        onWillUnmount(() => document.removeEventListener("keydown", this.onKeydown));
    }

    onKeydown(ev) {
        if (!document.querySelector(".o_ag_side") || document.querySelector(".modal.show, .modal-dialog")) {
            return;
        }
        const action = shortcutFor(ev);
        if (action && this[action](ev)) {
            ev.preventDefault();
        }
    }

    help() {
        openShortcutHelp(this.dialog);
        return true;
    }

    search() {
        const input = document.querySelector(".o_searchview_input");
        input?.focus();
        return Boolean(input);
    }

    /** Backlog: the add line of the first section; Board and other lists: the New button. */
    create() {
        const quick = document.querySelector(".o_ag_quick_input");
        if (quick) {
            quick.focus();
            return true;
        }
        const button = document.querySelector(".o-kanban-button-new, .o_list_button_add");
        button?.click();
        return Boolean(button);
    }

    /** The Backlog's own handler moves a focused row; on the Board a focused card opens its Move to sheet. */
    move() {
        const card = document.activeElement?.closest?.(".o_kanban_record");
        const link = card?.querySelector(".o_ag_move_to");
        link?.click();
        return Boolean(link);
    }
}

registry.category("main_components").add("agile_community.shortcuts", { Component: AgileShortcuts });
