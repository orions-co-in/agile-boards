import { Component, useProps, t } from "@odoo/owl";

// Status category -> icon, so status is never conveyed by colour alone.
export const AGILE_STATUS_ICONS = {
    backlog: "circle",
    ready: "circle",
    progress: "progress_activity",
    review: "visibility",
    done: "check",
    canceled: "block",
};

export class AgileLozenge extends Component {
    static template = "agile_community.Lozenge";
    props = useProps({
        label: t.string(),
        category: t.string().optional("backlog")});

    get category() {
        return this.props.category in AGILE_STATUS_ICONS ? this.props.category : "backlog";
    }

    get icon() {
        return AGILE_STATUS_ICONS[this.category];
    }
}

export class AgileAvatar extends Component {
    static template = "agile_community.Avatar";
    props = useProps({ name: t.string().optional("")});

    get initials() {
        const words = this.props.name.trim().split(/\s+/).filter(Boolean);
        if (!words.length) {
            return "?";
        }
        const first = words[0][0];
        const last = words.length > 1 ? words[words.length - 1][0] : "";
        return (first + last).toUpperCase();
    }

    get label() {
        return this.props.name || "Unassigned";
    }
}

export class AgileChip extends Component {
    static template = "agile_community.Chip";
    props = useProps({
        label: t.string(),
        active: t.boolean().optional(false),
        onClick: t.function().optional()});
}

export class AgileTypeDot extends Component {
    static template = "agile_community.TypeDot";
    props = useProps({ type: t.string().optional("task"), label: t.string().optional()});

    get type() {
        return ["epic", "story", "task", "bug"].includes(this.props.type) ? this.props.type : "task";
    }
}
