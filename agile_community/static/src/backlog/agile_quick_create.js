import { Component, useRef, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";

/** Add an issue at the bottom of a section: pick a type, type a title, optionally pick an assignee, press Enter. */
export class AgileQuickCreate extends Component {
    static template = "agile_community.QuickCreate";
    static props = {
        groupKey: String,
        label: String,
        types: Array,
        members: { type: Array, optional: true },
        typeId: { type: Number, optional: true },
        onTypeChange: Function,
        onCreate: Function,
    };

    setup() {
        this.inputRef = useRef("input");
        this.state = useState({ title: "", error: "", saving: false, userId: 0 });
    }

    get typeId() {
        return this.props.typeId ?? this.props.types[0]?.id;
    }

    async submit() {
        const title = this.state.title.trim();
        if (!title || this.state.saving) {
            return;
        }
        this.state.saving = true;
        this.state.error = "";
        try {
            await this.props.onCreate({ title, typeId: this.typeId, userId: this.state.userId });
            this.state.title = "";
        } catch (error) {
            this.state.error = error?.data?.message || error?.message || _t("Could not create the issue.");
        } finally {
            this.state.saving = false;
        }
    }

    onKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.submit();
        } else if (ev.key === "Escape") {
            this.state.title = "";
            this.state.error = "";
        }
    }

    onAssigneeChange(ev) {
        this.state.userId = Number(ev.target.value) || 0;
    }

    onTypeChange(ev) {
        this.props.onTypeChange(Number(ev.target.value));
    }
}
