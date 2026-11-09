import { Component, onWillUpdateProps, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

const PAUSE = 250;

/** Replace the typed fragment [start, end) with the accepted suggestion. */
export function applySuggestion(text, suggest, item) {
    const closing = [")", ",", "("].includes(item.insert);
    const tail = closing ? "" : " ";
    return {
        text: text.slice(0, suggest.start) + item.insert + tail + text.slice(suggest.end),
        cursor: suggest.start + item.insert.length + tail.length,
    };
}

const KEYWORDS = ["AND", "OR", "NOT", "IN", "IS", "EMPTY"];

/** A value as it is written in the query: quoted when it has spaces or is a keyword. */
export function quoteValue(value) {
    const plain = /^[\w.\-+:@#]+$/.test(value) && !KEYWORDS.includes(value.toUpperCase());
    return plain ? value : `"${value.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`;
}

/** The query text for Basic rows. A row still waiting for its value is left out. */
export function rowsToQuery(rows, matchAny, sort = "") {
    const parts = rows
        .filter((row) => row.field && (row.op.startsWith("IS ") || row.value !== ""))
        .map((row) =>
            row.op.startsWith("IS ")
                ? `${row.field} ${row.op}`
                : `${row.field} ${row.op} ${quoteValue(row.value)}`
        );
    const conditions = parts.join(matchAny ? " OR " : " AND ");
    return sort ? (conditions ? `${conditions} ${sort}` : sort) : conditions;
}

/** "12 issues match" in words; one is singular. */
export function countText(count) {
    return count === 1 ? _t("1 issue matches") : _t("%(count)s issues match", { count });
}

/**
 * The query bar: type `status = "In Progress" AND assignee = me`, see what can come next,
 * what the query means in words and how many issues it finds, or what is wrong with it.
 */
export class AgileQueryField extends Component {
    static template = "agile_community.AgileQueryField";
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.input = useRef("input");
        this.state = useState({
            text: this.props.record.data[this.props.name] || "",
            open: false,
            index: 0,
            suggest: { start: 0, end: 0, items: [] },
            ok: false,
            count: null,
            words: "",
            error: null,
            mode: "basic",
            options: [],
            rows: [],
            matchAny: false,
            basicOk: true,
            sort: "",
            blockers: [],
        });
        this.timer = null;
        this.dismissed = false;
        this.requestId = 0;
        onWillUpdateProps((next) => {
            const value = next.record.data[next.name] || "";
            if (value !== this.state.text && document.activeElement !== this.input.el) {
                this.state.text = value;
                this.assist(false);
            }
        });
        this.assist(false);
        this.loadOptions();
    }

    async loadOptions() {
        if (this.projectId) {
            this.state.options = await this.orm.call("agile.filter", "agile_query_options", [
                this.projectId,
            ]);
        }
    }

    get projectId() {
        const project = this.props.record.data.project_id;
        return project?.id ?? project?.[0] ?? false;
    }

    get statusText() {
        if (this.state.error) {
            return this.state.error.message;
        }
        if (this.state.ok && this.state.count !== null) {
            return countText(this.state.count);
        }
        return "";
    }

    get listId() {
        return `agile_query_list_${this.props.record.id || "new"}`;
    }

    optionFor(field) {
        return this.state.options.find((option) => option.field === field);
    }

    /** Rows follow the text unless the person is editing the rows themselves. */
    syncRows(result, fromRows) {
        const empty = !this.state.text.trim();
        this.state.basicOk = empty || !!result.rows;
        this.state.blockers = result.basic_blockers || [];
        if (fromRows) {
            return;
        }
        if (empty) {
            this.state.rows = [];
            this.state.matchAny = false;
            this.state.sort = "";
        } else if (result.rows) {
            this.state.sort = result.rows.sort || "";
            this.state.rows = result.rows.rows.map((row) => ({ ...row }));
            this.state.matchAny = result.rows.match_any;
        }
        if (!this.state.basicOk && this.state.mode === "basic" && !result.error) {
            this.state.mode = "advanced";
        }
    }

    async assist(open = true, fromRows = false) {
        const projectId = this.projectId;
        if (!projectId) {
            return;
        }
        const id = ++this.requestId;
        const cursor = this.input.el ? this.input.el.selectionStart : this.state.text.length;
        const result = await this.orm.call("agile.filter", "agile_query_assist", [
            projectId,
            this.state.text,
            cursor,
        ]);
        if (id !== this.requestId) {
            return; // a newer keystroke already asked
        }
        this.syncRows(result, fromRows);
        Object.assign(this.state, {
            ok: result.ok,
            count: result.count,
            words: result.words,
            error: result.error,
            suggest: result.suggest,
            index: 0,
            open: open && !this.dismissed && result.suggest.items.length > 0,
        });
    }

    schedule(open = true) {
        clearTimeout(this.timer);
        this.timer = setTimeout(() => this.assist(open), PAUSE);
    }

    onInput(ev) {
        this.state.text = ev.target.value;
        this.dismissed = false;
        this.props.record.update({ [this.props.name]: this.state.text });
        this.schedule(true);
    }

    onClick() {
        this.schedule(true);
    }

    onBlur() {
        // Let a click on a suggestion land before the list closes.
        setTimeout(() => (this.state.open = false), 120);
    }

    onKeydown(ev) {
        const items = this.state.suggest.items;
        if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
            if (!this.state.open) {
                this.assist(true);
            } else if (items.length) {
                const step = ev.key === "ArrowDown" ? 1 : -1;
                this.state.index = (this.state.index + step + items.length) % items.length;
            }
            ev.preventDefault();
        } else if ((ev.key === "Enter" || ev.key === "Tab") && this.state.open && items.length) {
            ev.preventDefault();
            this.accept(items[this.state.index]);
        } else if (ev.key === "Escape" && this.state.open) {
            ev.preventDefault();
            ev.stopPropagation();
            this.dismissed = true;
            this.state.open = false;
        } else if (ev.key === " " && ev.ctrlKey) {
            ev.preventDefault();
            this.dismissed = false;
            this.assist(true);
        }
    }

    accept(item) {
        const { text, cursor } = applySuggestion(this.state.text, this.state.suggest, item);
        this.state.text = text;
        this.props.record.update({ [this.props.name]: text });
        this.state.open = false;
        const el = this.input.el;
        el.value = text;
        el.focus();
        el.setSelectionRange(cursor, cursor);
        this.assist(true);
    }

    setMode(mode) {
        this.state.mode = mode;
    }

    rowsChanged() {
        this.state.text = rowsToQuery(this.state.rows, this.state.matchAny, this.state.sort);
        this.props.record.update({ [this.props.name]: this.state.text });
        this.dismissed = true;
        this.assist(false, true);
    }

    addRow(option) {
        const op = option.ops[0].op;
        this.state.rows.push({
            field: option.field,
            op,
            value: option.values?.length && !op.startsWith("IS ") ? option.values[0] : "",
        });
        this.rowsChanged();
    }

    clearSort() {
        this.state.sort = "";
        this.rowsChanged();
    }

    get blockerText() {
        return this.state.blockers.length ? this.state.blockers.join(", ") : "";
    }

    removeRow(index) {
        this.state.rows.splice(index, 1);
        this.rowsChanged();
    }

    onRowField(row, ev) {
        const option = this.optionFor(ev.target.value);
        row.field = option.field;
        row.op = option.ops[0].op;
        row.value = option.values?.length ? option.values[0] : "";
        this.rowsChanged();
    }

    onRowOp(row, ev) {
        row.op = ev.target.value;
        this.rowsChanged();
    }

    onRowValue(row, ev) {
        row.value = ev.target.value;
        this.rowsChanged();
    }

    onMatchAny(ev) {
        this.state.matchAny = ev.target.checked;
        this.rowsChanged();
    }

    valuesFor(row) {
        const values = this.optionFor(row.field)?.values || [];
        return row.value && !values.includes(row.value) ? [row.value, ...values] : values;
    }

    onExample() {
        this.accept({ insert: 'type = Bug AND assignee = me AND sprint = currentSprint AND statusCategory != Done' });
    }
}

registry.category("fields").add("agile_query", {
    component: AgileQueryField,
    displayName: _t("Agile query"),
    supportedTypes: ["char"],
});
