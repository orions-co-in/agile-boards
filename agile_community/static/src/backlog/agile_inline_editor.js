import { signal } from "@odoo/owl";
import { Component, onMounted, proxy, useProps, t } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";


/**
 * The small editor that opens on a backlog cell (spec section 12): a number box
 * or a pick list. Enter saves, Esc cancels, a server refusal shows under the
 * field and keeps the old value.
 */
export class AgileInlineEditor extends Component {
    static template = "agile_community.InlineEditor";
    props = useProps({
        label: t.string(),
        kind: t.string(), // "number" | "select"
        value: t.any().optional(),
        options: t.array().optional(),
        onSave: t.function(),
        close: t.function()});

    setup() {
        this.inputRef = signal.ref();
        this.state = proxy({ value: this.props.value ?? "", error: "", saving: false });
        onMounted(() => {
            const el = this.inputRef();
            el?.focus();
            el?.select?.();
        });
    }

    /** Turn what was typed into the value to save, or an error to show. */
    parse() {
        if (this.props.kind === "number") {
            const raw = String(this.state.value).trim();
            if (raw === "") {
                return { value: null }; // an empty box means "not estimated"
            }
            const points = Number(raw);
            if (!Number.isFinite(points) || points < 0) {
                return { error: _t("Points must be a number of 0 or more.") };
            }
            return { value: points };
        }
        const id = Number(this.state.value);
        return { value: id || false };
    }

    async save() {
        if (this.state.saving) {
            return;
        }
        const parsed = this.parse();
        if (parsed.error) {
            this.state.error = parsed.error;
            return;
        }
        this.state.saving = true;
        this.state.error = "";
        try {
            await this.props.onSave(parsed.value);
            this.props.close();
        } catch (error) {
            this.state.error = error?.data?.message || error?.message || _t("Could not save.");
        } finally {
            this.state.saving = false;
        }
    }

    onKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.save();
        } else if (ev.key === "Escape") {
            ev.preventDefault();
            ev.stopPropagation();
            this.props.close();
        }
    }
}
