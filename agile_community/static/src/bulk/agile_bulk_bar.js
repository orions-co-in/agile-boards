import { Component, onWillStart, onWillUpdateProps, proxy, useProps, t } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";

export const BULK_LIMIT = 100;

/** The result line, in words: "Moved 4 of 5 issues to Sprint 3. 1 was refused." */
export function resultText(change, label, done, total, refused) {
    const what = {
        assignee: label ? _t("assigned to %(name)s", { name: label }) : _t("unassigned"),
        sprint: label ? _t("moved to %(name)s", { name: label }) : _t("moved to the Backlog"),
        status: _t("moved to %(name)s", { name: label }),
        label_add: _t("labelled %(name)s", { name: label }),
        label_remove: _t("unlabelled %(name)s", { name: label }),
        type: _t("set to the type %(name)s", { name: label }),
        priority: _t("set to %(name)s", { name: label }),
        due: label ? _t("given the due date %(name)s", { name: label }) : _t("cleared of their due date"),
        watch: _t("added to your watch list"),
        unwatch: _t("removed from your watch list"),
    }[change];
    const base = _t("%(done)s of %(total)s issues %(what)s.", { done, total, what });
    if (!refused) {
        return base;
    }
    return refused === 1 ? _t("%(base)s 1 was refused.", { base }) : _t("%(base)s %(count)s were refused.", { base, count: refused });
}

/**
 * The bar under the Backlog and the Board when issues are selected (S-931): one change for all of them.
 * The server handles each issue by the usual rules and says which were refused and why.
 */
export class AgileBulkBar extends Component {
    static template = "agile_community.BulkBar";
    static components = { Dropdown, DropdownItem };
    props = useProps({ projectId: t.number(), ids: t.array(), onDone: t.function(), onClear: t.function()});

    setup() {
        this.orm = useService("orm");
        this.state = proxy({
            options: { members: [], sprints: [], statuses: [], tags: [], types: [], priorities: [] },
            busy: false,
            confirm: null,
            result: null,
            whyOpen: false,
        });
        onWillStart(() => this.loadOptions());
        // A sprint, label or member added since the bar mounted must show up: reload the
        // choices each time a new selection starts.
        onWillUpdateProps((next) => {
            if (!this.props.ids.length && next.ids.length) {
                return this.loadOptions();
            }
        });
    }

    async loadOptions() {
        try {
            this.state.options = await this.orm.call("project.project", "agile_bulk_options", [[this.props.projectId]]);
        } catch {
            // Without the choices the bar still shows the count and Clear.
        }
    }

    get count() {
        return this.props.ids.length;
    }

    get countText() {
        return this.count === 1 ? _t("1 selected") : _t("%(count)s selected", { count: this.count });
    }

    /** Run one change; a sprint change that takes issues out of a running sprint asks first. */
    async run(change, value, label, confirmed = false) {
        if (this.state.busy) {
            return;
        }
        if (this.count > BULK_LIMIT) {
            this.state.result = { text: _t("Select up to %(max)s issues.", { max: BULK_LIMIT }), refused: [], restore: [] };
            return;
        }
        this.state.busy = true;
        this.state.confirm = null;
        try {
            const result = await this.orm.call("project.task", "agile_bulk_update", [this.props.ids, change, value ?? false], {
                confirmed,
            });
            if (result.needs_confirm) {
                this.state.confirm = { change, value, label, count: result.needs_confirm, sprint: result.sprint };
                return;
            }
            this.state.result = {
                text: resultText(change, label, result.changed.length, this.count, result.refused.length),
                refused: result.refused,
                restore: change === "status" ? [] : result.restore,
                noUndo: change === "status" && result.changed.length > 0,
            };
            this.state.whyOpen = false;
            await this.props.onDone({ changed: result.changed, refused: result.refused.map((item) => item.id) });
        } catch (error) {
            this.state.result = {
                text: error?.data?.message || _t("Could not apply the change. Try again."),
                refused: [],
                restore: [],
            };
        } finally {
            this.state.busy = false;
        }
    }

    onDue(ev) {
        const value = ev.target.value;
        return value ? this.run("due", value, value) : null;
    }

    dismiss() {
        this.state.result = null;
        this.state.whyOpen = false;
    }

    confirmMove() {
        const { change, value, label } = this.state.confirm;
        return this.run(change, value, label, true);
    }

    async undo() {
        const restore = this.state.result?.restore || [];
        if (!restore.length) {
            return;
        }
        this.state.busy = true;
        try {
            const result = await this.orm.call("project.task", "agile_bulk_restore", [restore]);
            this.state.result = { text: _t("Undone for %(count)s issues.", { count: result.undone.length }), refused: [], restore: [] };
            await this.props.onDone({ changed: result.undone, refused: [] });
        } finally {
            this.state.busy = false;
        }
    }
}
