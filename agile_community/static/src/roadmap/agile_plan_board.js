import { Component, onMounted, onPatched, onWillUpdateProps, useRef, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { planDate } from "./agile_plan_scenario";

/** "34 of 30 points: over by 4" for a board cell, in words as well as colour. */
export function cellText(cell) {
    if (!cell) {
        return _t("No sprint");
    }
    if (!cell.capacity) {
        return cell.planned ? _t("%s points planned, no capacity set", cell.planned) : _t("No capacity set");
    }
    const text = _t("%(planned)s of %(capacity)s points", { planned: cell.planned, capacity: cell.capacity });
    return cell.over ? `${text}: ${_t("over by %s", cell.over)}` : text;
}

/** The sprint a card moves to for Alt+Left or Alt+Right, or null at the ends of the team's sprints. */
export function neighbourOrdinal(card, key, sprintCount) {
    const target = card.ordinal + (key === "ArrowRight" ? 1 : key === "ArrowLeft" ? -1 : 0);
    return target === card.ordinal || target < 0 || target >= sprintCount ? null : target;
}

/** Arrow from the right-middle of one card to the left-middle of the next, as an SVG path with a small curve. */
export function connectorPath(from, to) {
    const dx = Math.max(Math.abs(to.x - from.x) / 2, 24);
    return `M ${from.x} ${from.y} C ${from.x + dx} ${from.y}, ${to.x - dx} ${to.y}, ${to.x} ${to.y}`;
}

/** The program board of one scenario: teams as rows, each team's next sprints as columns. */
export class AgilePlanBoard extends Component {
    static template = "agile_community.PlanBoard";
    static props = { scenarioId: Number, onChange: Function };

    setup() {
        this.orm = useService("orm");
        this.ui = useService("ui");
        this.root = useRef("root");
        this.state = useState({ data: null, error: null, notice: null, offset: 0, team: 0, lines: [], dragging: null });
        onMounted(() => this.load(this.props.scenarioId));
        onWillUpdateProps((next) => next.scenarioId !== this.props.scenarioId && this.load(next.scenarioId));
        onPatched(() => this.drawLines());
    }

    async load(id, offset = this.state.offset) {
        this.state.error = null;
        try {
            const data = await this.orm.call("agile.plan.scenario", "scenario_board", [id, offset]);
            for (const team of data.teams) {
                for (const card of team.cards) {
                    card.team_id = team.id;
                }
            }
            this.state.data = data;
            this.state.offset = offset;
        } catch {
            this.state.data = null;
            this.state.error = _t("The board did not load. Try again.");
        }
    }

    get teams() {
        const teams = this.state.data.teams;
        return this.ui.isSmall ? teams.slice(this.state.team, this.state.team + 1) : teams;
    }

    get maxOffset() {
        return Math.max(this.state.data.max_sprints - this.state.data.columns, 0);
    }

    cellText(cell) {
        return cellText(cell);
    }

    planDate(iso) {
        return iso ? planDate(iso) : "";
    }

    errorText(error, fallback) {
        return error?.data?.message || fallback;
    }

    cardLabel(card) {
        const parts = [`${card.key} ${card.name}`, `${this.planDate(card.start)} to ${this.planDate(card.end)}`];
        if (card.late) {
            parts.push(_t("Starts before a blocker ends"));
        }
        return parts.join(", ");
    }

    blockedText(card) {
        return card.blocked_by.map((b) => `${b.key} ${_t("ends")} ${this.planDate(b.end)}`).join(", ");
    }

    sprintOptions(team) {
        return team.cells.filter(Boolean);
    }

    async page(step) {
        const offset = Math.min(Math.max(this.state.offset + step, 0), this.maxOffset);
        await this.load(this.props.scenarioId, offset);
    }

    async move(card, ordinal) {
        this.state.notice = null;
        try {
            await this.orm.call("agile.plan.scenario", "scenario_move_epic", [this.props.scenarioId, card.epic_id, ordinal]);
            this.state.notice = _t("%(key)s now starts in a later or earlier sprint of this scenario.", { key: card.key });
        } catch (error) {
            this.state.notice = this.errorText(error, _t("The epic was not moved."));
        }
        await this.load(this.props.scenarioId);
        this.props.onChange();
    }

    async onMoveSelect(card, ev) {
        const value = ev.target.value;
        ev.target.value = "";
        if (value !== "") {
            await this.move(card, Number(value));
        }
    }

    onCardKeydown(team, card, ev) {
        if (!ev.altKey || !card.can_move) {
            return;
        }
        const target = neighbourOrdinal(card, ev.key, team.sprint_count);
        if (target !== null) {
            ev.preventDefault();
            this.move(card, target);
        }
    }

    onDragStart(card, ev) {
        this.state.dragging = card;
        ev.dataTransfer.effectAllowed = "move";
        ev.dataTransfer.setData("text/plain", String(card.epic_id));
    }

    onDragOver(team, cell, ev) {
        if (this.state.dragging && cell && this.state.dragging.can_move && this.state.dragging.team_id === team.id) {
            ev.preventDefault();
        }
    }

    async onDrop(team, cell, ev) {
        ev.preventDefault();
        const card = this.state.dragging;
        this.state.dragging = null;
        if (card && cell && card.team_id === team.id && card.can_move && cell.ordinal !== card.ordinal) {
            await this.move(card, cell.ordinal);
        }
    }

    /** Blocker-to-blocked arrows between cards on screen, measured from the page. */
    drawLines() {
        const root = this.root.el;
        if (!root || !this.state.data || this.ui.isSmall) {
            return;
        }
        const origin = root.querySelector(".o_ag_pb_grid")?.getBoundingClientRect();
        if (!origin) {
            return;
        }
        const point = (el, side) => {
            const r = el.getBoundingClientRect();
            return { x: (side === "right" ? r.right : r.left) - origin.left, y: r.top + r.height / 2 - origin.top };
        };
        const lines = [];
        for (const team of this.state.data.teams) {
            for (const card of team.cards) {
                const to = root.querySelector(`.o_ag_pb_card[data-epic="${card.epic_id}"]`);
                for (const blocker of card.blocked_by) {
                    const from = blocker.epic_id && root.querySelector(`.o_ag_pb_card[data-epic="${blocker.epic_id}"]`);
                    if (from && to) {
                        lines.push({ d: connectorPath(point(from, "right"), point(to, "left")), late: blocker.late });
                    }
                }
            }
        }
        if (JSON.stringify(lines) !== JSON.stringify(this.state.lines)) {
            this.state.lines = lines;
        }
    }
}
