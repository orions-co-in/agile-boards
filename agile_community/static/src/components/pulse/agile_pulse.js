import { Component, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { deserializeDate } from "@web/core/l10n/dates";
import { unitWord } from "../../estimate_unit";

const MIN_CELLS = 5;
const MAX_CELLS = 21;
const SHORT_DATE = { weekday: "short", day: "numeric", month: "short" };

export function formatPoints(value) {
    return String(Math.round((value || 0) * 100) / 100);
}

export function signedPoints(value) {
    return (value > 0 ? "+" : "") + formatPoints(value);
}

function shortDate(isoDate) {
    return deserializeDate(isoDate).toLocaleString(SHORT_DATE);
}

/**
 * The sprint pulse: one cell per sprint day (teal height = points left,
 * hatched = future, plum outline = today, amber diamond = scope change) and a
 * three-phrase caption. Pace is always written in words, never colour alone.
 */
export class AgilePulse extends Component {
    static template = "agile_community.Pulse";
    static props = {
        pulse: Object,
        onOpenSprint: { type: Function, optional: true },
        onPlanSprint: { type: Function, optional: true },
    };

    setup() {
        this.state = useState({ focus: null });
    }

    get unit() {
        return unitWord(this.props.pulse.estimate_unit);
    }

    get sprint() {
        return this.props.pulse.sprint || null;
    }

    get stripState() {
        return this.props.pulse.state;
    }

    get hasStrip() {
        return ["active", "planned", "waiting", "completed"].includes(this.stripState);
    }

    get isEmptyState() {
        return this.stripState === "none";
    }

    get days() {
        return this.props.pulse.days || [];
    }

    get dayOfSprint() {
        const sprint = this.sprint;
        if (!sprint) {
            return 0;
        }
        const today = this.props.pulse.today;
        const start = deserializeDate(sprint.date_start);
        const diff = Math.floor(deserializeDate(today).diff(start, "days").days);
        return Math.min(Math.max(diff + 1, 1), sprint.total_days);
    }

    get maxPoints() {
        const sprint = this.sprint;
        const values = [sprint?.committed_points || 0, 1];
        for (const day of this.days) {
            values.push(day.points_left || 0, day.ideal_left || 0);
        }
        return Math.max(...values);
    }

    get cells() {
        const max = this.maxPoints;
        if (!this.days.length) {
            return this.syntheticCells();
        }
        return this.days.map((day, index) => {
            const known = day.points_left !== null && day.points_left !== undefined;
            const date = shortDate(day.date);
            let label;
            if (day.is_future) {
                label = _t("%(date)s: ideal %(ideal)s %(unit)s left", { unit: this.unit,
                    date,
                    ideal: formatPoints(day.ideal_left),
                });
            } else if (known) {
                label = _t("%(date)s: %(left)s %(unit)s left, ideal %(ideal)s", { unit: this.unit,
                    date,
                    left: formatPoints(day.points_left),
                    ideal: formatPoints(day.ideal_left),
                });
            } else {
                label = _t("%(date)s: no snapshot", { date });
            }
            if (day.scope_changed) {
                label += ". " + _t("%(delta)s %(unit)s of scope change", { unit: this.unit, delta: signedPoints(day.scope_points) });
            }
            return {
                index,
                key: day.date,
                label,
                fill: day.is_future ? (day.ideal_left / max) * 100 : known ? (day.points_left / max) * 100 : 0,
                idealAt: day.is_future ? null : (day.ideal_left / max) * 100,
                today: day.is_today,
                future: day.is_future,
                weekend: day.is_weekend,
                estimated: day.estimated,
                scope: day.scope_changed,
            };
        });
    }

    syntheticCells() {
        const sprint = this.sprint;
        const count = Math.min(Math.max(sprint?.total_days || MAX_CELLS / 2, MIN_CELLS), MAX_CELLS);
        const waiting = this.stripState === "waiting";
        return Array.from({ length: count }, (_unused, index) => ({
            index,
            key: String(index),
            label: waiting
                ? _t("Day %(day)s", { day: index + 1 })
                : _t("Planned day %(day)s", { day: index + 1 }),
            fill: 100 * (1 - index / count),
            idealAt: null,
            today: waiting && index === this.dayOfSprint - 1,
            future: true,
            weekend: false,
            estimated: false,
            scope: false,
        }));
    }

    get tabStop() {
        if (this.state.focus !== null) {
            return this.state.focus;
        }
        return Math.max(this.cells.findIndex((cell) => cell.today), 0);
    }

    get tip() {
        const index = this.state.focus;
        return index === null ? "" : this.cells[index]?.label || "";
    }

    get ariaLabel() {
        return this.captionParts.map((part) => part.text).join(". ");
    }

    get paceClass() {
        const pace = this.props.pulse.pace;
        return pace && pace.status === "behind" ? "o_ag_pace_behind" : "";
    }

    /** Three phrases: where we are, how the pace looks, what changed. */
    get captionParts() {
        const sprint = this.sprint;
        const pulse = this.props.pulse;
        if (!sprint) {
            return [];
        }
        const parts = [];
        const name = sprint.name;
        switch (this.stripState) {
            case "planned": {
                parts.push({
                    text: _t("%(name)s starts %(date)s", { name, date: shortDate(sprint.date_start) }),
                    sprint: true,
                });
                const planned = formatPoints(sprint.planned_points);
                parts.push({
                    text: sprint.capacity_points
                        ? _t("%(planned)s %(unit)s planned, team capacity %(capacity)s", { unit: this.unit,
                              planned,
                              capacity: formatPoints(sprint.capacity_points),
                          })
                        : _t("%(planned)s %(unit)s planned", { unit: this.unit, planned }),
                });
                if (pulse.can_manage) {
                    parts.push({ text: _t("Start the sprint"), action: "open" });
                }
                break;
            }
            case "waiting":
                parts.push({
                    text: _t("%(name)s day %(day)s of %(total)s", {
                        name,
                        day: this.dayOfSprint,
                        total: sprint.total_days,
                    }),
                    sprint: true,
                });
                parts.push({ text: _t("Waiting for the first daily snapshot") });
                parts.push({ text: _t("Pace shows from day 2") });
                break;
            case "completed": {
                parts.push({ text: _t("%(name)s completed", { name }), sprint: true });
                parts.push({
                    text: _t("%(done)s of %(committed)s %(unit)s done", { unit: this.unit,
                        done: formatPoints(sprint.completed_points),
                        committed: formatPoints(sprint.committed_points),
                    }),
                });
                const carried = Math.max(sprint.committed_points - sprint.completed_points, 0);
                parts.push({
                    text: carried
                        ? _t("%(points)s %(unit)s carried over", { unit: this.unit, points: formatPoints(carried) })
                        : _t("Nothing carried over"),
                });
                break;
            }
            default: {
                const today = this.days.find((day) => day.is_today);
                parts.push({
                    text: _t("%(name)s day %(day)s of %(total)s", {
                        name,
                        day: today ? today.day_number : this.dayOfSprint,
                        total: sprint.total_days,
                    }),
                    sprint: true,
                });
                parts.push(this.paceText());
                parts.push({ text: this.scopeText() });
            }
        }
        return parts;
    }

    paceText() {
        const pace = this.props.pulse.pace;
        if (!pace) {
            return { text: _t("Pace shows once estimates are counted") };
        }
        const args = { unit: this.unit, left: formatPoints(pace.points_left), ideal: formatPoints(pace.ideal_left) };
        const delta = formatPoints(Math.abs(pace.delta));
        let text;
        if (pace.status === "behind") {
            text = _t("%(left)s %(unit)s left, ideal %(ideal)s: behind by %(delta)s", { unit: this.unit, ...args, delta });
        } else if (pace.status === "ahead") {
            text = _t("%(left)s %(unit)s left, ideal %(ideal)s: ahead by %(delta)s", { unit: this.unit, ...args, delta });
        } else {
            text = _t("%(left)s %(unit)s left, ideal %(ideal)s: on pace", args);
        }
        return { text, pace: true };
    }

    scopeText() {
        const changes = this.props.pulse.scope_changes || [];
        if (!changes.length) {
            return _t("No scope changes");
        }
        if (changes.length === 1) {
            const day = this.days.find((d) => d.date === changes[0].date);
            return _t("1 scope change on day %(day)s (%(delta)s)", {
                day: day ? day.day_number : "?",
                delta: signedPoints(changes[0].points_delta),
            });
        }
        const net = changes.reduce((sum, change) => sum + change.points_delta, 0);
        return _t("%(count)s scope changes, net %(delta)s", {
            count: changes.length,
            delta: signedPoints(net),
        });
    }

    get tableRows() {
        return this.days.map((day) => ({
            date: shortDate(day.date),
            left: day.points_left === null ? "" : formatPoints(day.points_left),
            ideal: formatPoints(day.ideal_left),
        }));
    }

    onCellFocus(index) {
        this.state.focus = index;
    }

    onCellBlur() {
        this.state.focus = null;
    }

    onKeydown(ev) {
        const step = { ArrowRight: 1, ArrowLeft: -1, Home: -Infinity, End: Infinity }[ev.key];
        if (step === undefined) {
            return;
        }
        ev.preventDefault();
        const cells = this.cells;
        const current = this.state.focus ?? cells.findIndex((cell) => cell.today);
        const base = current < 0 ? 0 : current;
        const next = Math.min(Math.max(base + step, 0), cells.length - 1);
        this.state.focus = next;
        ev.currentTarget.querySelector(`[data-cell="${next}"]`)?.focus();
    }

    onPartClick(part) {
        if (part.sprint || part.action === "open") {
            this.props.onOpenSprint?.(this.sprint.id);
        }
    }
}
