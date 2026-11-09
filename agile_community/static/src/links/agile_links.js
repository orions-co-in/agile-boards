import { Component, onPatched, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/** The link types in the order the Add link select lists them. */
export function linkKinds() {
    return [
        { key: "blocks", label: _t("Blocks"), blocking: true },
        { key: "blocked_by", label: _t("Is blocked by"), blocking: true },
        { key: "clones", label: _t("Clones") },
        { key: "cloned_by", label: _t("Is cloned by") },
        { key: "duplicates", label: _t("Duplicates") },
        { key: "duplicated_by", label: _t("Is duplicated by") },
        { key: "relates", label: _t("Relates to") },
    ];
}

/**
 * The Links panel (I-1013): every link of an issue in one place, grouped by the sentence it reads
 * from this side. It lives on the issue form, so the board drawer shows the same panel.
 */
export class AgileLinks extends Component {
    static template = "agile_community.Links";
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.addRef = useRef("addButton");
        this.searchRef = useRef("search");
        this.state = useState({
            loading: true,
            error: null,
            data: null,
            adding: false,
            kind: "blocks",
            query: "",
            results: [],
            busy: false,
            notice: "",
            problem: "",
        });
        this.searchToken = 0;
        this.focusAdd = false;
        this.focusSearch = false;
        // Focus returns to Add link once the box has been replaced by it.
        onPatched(() => {
            if (this.focusSearch && this.searchRef.el) {
                this.focusSearch = false;
                this.searchRef.el.focus();
            }
            if (this.focusAdd && this.addRef.el) {
                this.focusAdd = false;
                this.addRef.el.focus();
            }
        });
        this.loadedFor = null;
        // Load when the form shows a saved issue; a new issue has nothing to link yet.
        this.ensureLoaded();
    }

    get resId() {
        return this.props.record.resId;
    }

    get kinds() {
        const blocking = this.state.data?.allow_blocking;
        return linkKinds().filter((kind) => blocking || !kind.blocking);
    }

    get canAdd() {
        return Boolean(this.resId && this.state.data?.can_edit);
    }

    get isEmpty() {
        return !this.state.data.groups.length && !this.state.data.hidden;
    }

    get hiddenText() {
        const count = this.state.data.hidden;
        return count === 1
            ? _t("1 more link you cannot see.")
            : _t("%(count)s more links you cannot see.", { count });
    }

    async ensureLoaded() {
        if (!this.resId || this.loadedFor === this.resId) {
            this.state.loading = false;
            return;
        }
        this.loadedFor = this.resId;
        this.state.loading = true;
        this.state.error = null;
        try {
            this.state.data = await this.orm.call("project.task", "agile_links_data", [[this.resId]]);
        } catch {
            this.state.error = _t("The links did not load. Try again.");
        }
        this.state.loading = false;
    }

    retry() {
        this.loadedFor = null;
        return this.ensureLoaded();
    }

    openAdd() {
        this.state.adding = true;
        this.state.problem = "";
        this.state.kind = this.kinds[0].key;
        this.state.query = "";
        this.state.results = [];
        this.focusSearch = true;
    }

    cancelAdd() {
        this.state.adding = false;
        this.state.problem = "";
        this.focusAdd = true;
    }

    async onInput(ev) {
        this.state.query = ev.target.value;
        this.state.problem = "";
        const token = ++this.searchToken;
        const text = this.state.query.trim();
        if (!text) {
            this.state.results = [];
            return;
        }
        const rows = await this.orm.searchRead(
            "project.task",
            [
                ["agile_issue", "=", true],
                ["id", "!=", this.resId],
                "|",
                ["issue_key", "ilike", text],
                ["name", "ilike", text],
            ],
            ["issue_key", "name", "project_id"],
            { limit: 8 }
        );
        if (token === this.searchToken) {
            this.state.results = rows;
        }
    }

    onSearchKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            if (this.state.results.length) {
                this.add(this.state.results[0]);
            }
        } else if (ev.key === "ArrowDown") {
            ev.preventDefault();
            this.searchRef.el?.parentElement.querySelector(".o_ag_links_result")?.focus();
        }
    }

    onBoxKeydown(ev) {
        if (ev.key === "Escape") {
            ev.stopPropagation();
            this.cancelAdd();
        }
    }

    onResultKeydown(ev) {
        const items = [...ev.currentTarget.parentElement.querySelectorAll(".o_ag_links_result")];
        const index = items.indexOf(ev.currentTarget);
        if (ev.key === "ArrowDown") {
            ev.preventDefault();
            items[index + 1]?.focus();
        } else if (ev.key === "ArrowUp") {
            ev.preventDefault();
            (items[index - 1] || this.searchRef.el)?.focus();
        }
    }

    labelFor(kind) {
        return linkKinds().find((item) => item.key === kind)?.label || kind;
    }

    async call(method, kind, otherId) {
        this.state.busy = true;
        try {
            this.state.data = await this.orm.call("project.task", method, [[this.resId], kind, otherId]);
            return true;
        } catch (error) {
            this.state.problem = error.data?.message || _t("The link could not be saved. Try again.");
            return false;
        } finally {
            this.state.busy = false;
        }
    }

    /** The Add link button: take the first match, or say the typed key was not found. */
    async submit() {
        const text = this.state.query.trim();
        if (this.state.results.length) {
            return this.add(this.state.results[0]);
        }
        this.state.problem = _t("No issue %(key)s found that you can link.", {
            key: text ? text.toUpperCase() : _t("with that key"),
        });
    }

    async add(issue) {
        if (this.state.busy) {
            return;
        }
        const kind = this.state.kind;
        if (await this.call("agile_add_link", kind, issue.id)) {
            this.state.notice = _t("Link added: %(kind)s %(key)s", {
                kind: this.labelFor(kind),
                key: issue.issue_key,
            });
            this.cancelAdd();
        }
    }

    async remove(item) {
        if (this.state.busy) {
            return;
        }
        if (await this.call("agile_remove_link", item.kind, item.id)) {
            this.state.notice = _t("Link removed: %(key)s", { key: item.key });
            this.focusAdd = true;
        }
    }

    open(item) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "project.task",
            res_id: item.id,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("fields").add("agile_links", {
    component: AgileLinks,
    supportedTypes: ["many2many"],
});
