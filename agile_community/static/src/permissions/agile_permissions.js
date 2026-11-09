import { Component, onMounted, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { Layout } from "@web/search/layout";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

/** The question asked before a scheme changes: who gains what, and that it applies at once. */
export function switchQuestion(project, scheme) {
    return _t("Switch %(project)s to %(scheme)s? %(sentence)s This takes effect now for everyone.", {
        project,
        scheme: scheme.label,
        sentence: scheme.sentence,
    });
}

/** The permission scheme page (C-943): pick a scheme and read what each role may do. */
export class AgilePermissions extends Component {
    static template = "agile_community.Permissions";
    static components = { Layout };
    static props = ["*"];
    // The breadcrumb name when the page is restored from its address.
    static displayName = _t("Permissions");

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.display = { controlPanel: {} };
        this.state = useState({ loading: true, error: null, data: null, busy: false, viewing: null, draft: {} });
        onMounted(() => this.load());
    }

    get projectId() {
        const action = this.props.action || {};
        return action.params?.project_id || action.context?.active_id;
    }

    async load() {
        this.state.loading = true;
        this.state.error = null;
        try {
            this.state.data = await this.orm.call("agile.permissions", "permissions_data", [this.projectId]);
            this.state.viewing = this.state.data.scheme;
            this.resetDraft();
        } catch (error) {
            this.state.error = error.data?.message || _t("The permissions page did not load. Try again.");
        }
        this.state.loading = false;
    }

    /** The Custom grants as saved: {action: [roles]}, the starting point for edits. */
    resetDraft() {
        const draft = {};
        for (const row of this.state.data.matrix.custom || []) {
            if (row.editable) {
                draft[row.key] = [...row.grants];
            }
        }
        this.state.draft = draft;
    }

    /** Checkboxes show only on Custom while it is the scheme in use; the other schemes are read only. */
    get editing() {
        return this.state.viewing === "custom" && this.state.data.scheme === "custom";
    }

    get dirty() {
        const saved = this.state.data.matrix.custom || [];
        return saved.some((row) => row.editable && [...row.grants].sort().join() !== [...this.state.draft[row.key]].sort().join());
    }

    granted(row, role) {
        return this.state.draft[row.key].includes(role);
    }

    toggle(row, role) {
        const roles = this.state.draft[row.key];
        this.state.draft[row.key] = roles.includes(role) ? roles.filter((r) => r !== role) : [...roles, role];
    }

    async saveCustom() {
        this.state.busy = true;
        this.state.error = null;
        try {
            this.state.data = await this.orm.call("agile.permissions", "set_custom", [this.projectId, this.state.draft]);
            this.resetDraft();
        } catch (error) {
            this.state.error = error.data?.message || _t("Could not save the custom scheme. Try again.");
        }
        this.state.busy = false;
    }

    get rows() {
        return this.state.data ? this.state.data.matrix[this.state.viewing] : [];
    }

    choose(scheme) {
        if (this.state.busy || scheme.key === this.state.data.scheme) {
            this.state.viewing = scheme.key;
            return;
        }
        this.state.viewing = scheme.key;
        this.dialog.add(ConfirmationDialog, {
            title: _t("Change the permission scheme"),
            body: switchQuestion(this.state.data.project.name, scheme),
            confirmLabel: _t("Switch scheme"),
            confirm: () => this.apply(scheme),
            cancel: () => {
                this.state.viewing = this.state.data.scheme;
            },
        });
    }

    async apply(scheme) {
        this.state.busy = true;
        this.state.error = null;
        try {
            this.state.data = await this.orm.call("agile.permissions", "set_scheme", [this.projectId, scheme.key]);
            this.state.viewing = this.state.data.scheme;
            this.resetDraft();
        } catch (error) {
            this.state.error = _t("Could not switch the scheme. Try again.");
            this.state.viewing = this.state.data.scheme;
        }
        this.state.busy = false;
    }
}

registry.category("actions").add("agile_community.permissions", AgilePermissions);
