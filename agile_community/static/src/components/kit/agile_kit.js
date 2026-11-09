import { Component } from "@odoo/owl";

// Status category -> icon, so status is never conveyed by colour alone.
export const AGILE_STATUS_ICONS = {
    backlog: "fa-circle-o",
    ready: "fa-circle",
    progress: "fa-spinner",
    review: "fa-eye",
    done: "fa-check",
    canceled: "fa-ban",
};

export class AgileLozenge extends Component {
    static template = "agile_community.Lozenge";
    static props = {
        label: String,
        category: { type: String, optional: true },
    };
    static defaultProps = { category: "backlog" };

    get category() {
        return this.props.category in AGILE_STATUS_ICONS ? this.props.category : "backlog";
    }

    get icon() {
        return AGILE_STATUS_ICONS[this.category];
    }
}

export class AgileAvatar extends Component {
    static template = "agile_community.Avatar";
    static props = { name: { type: String, optional: true } };
    static defaultProps = { name: "" };

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
    static props = {
        label: String,
        active: { type: Boolean, optional: true },
        onClick: { type: Function, optional: true },
    };
    static defaultProps = { active: false };
}

export class AgileTypeDot extends Component {
    static template = "agile_community.TypeDot";
    static props = { type: { type: String, optional: true }, label: { type: String, optional: true } };
    static defaultProps = { type: "task" };

    get type() {
        return ["epic", "story", "task", "bug"].includes(this.props.type) ? this.props.type : "task";
    }
}
