const CHART_W = 400;
const CHART_H = 180;
// Room around the plot for the axis numbers and names.
const LEFT = 36;
const RIGHT = 10;
const TOP = 12;
const BOTTOM = 34;

/** Running totals of a daily series. */
export function cumulative(values) {
    let total = 0;
    return values.map((value) => (total += value));
}

/** "5 Oct" for a day given as YYYY-MM-DD; the text itself if it is not a date. */
export function dayLabel(day) {
    const date = new Date(`${day}T00:00:00`);
    return Number.isNaN(date.getTime())
        ? String(day)
        : date.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/**
 * Everything the Created and resolved chart draws: the two lines (scaled to one shared maximum so
 * the gap between them is the work still open), the axes with their numbers, and one entry per day
 * for the hover readout.
 */
export function flowLines(flow) {
    const created = cumulative(flow.created);
    const resolved = cumulative(flow.resolved);
    const max = Math.max(1, ...created, ...resolved);
    const plotW = CHART_W - LEFT - RIGHT;
    const plotH = CHART_H - TOP - BOTTOM;
    const count = flow.days.length;
    const step = count > 1 ? plotW / (count - 1) : 0;
    const xAt = (index) => LEFT + index * step;
    const yAt = (value) => TOP + plotH - (value / max) * plotH;
    const toPoints = (series) =>
        series.map((value, index) => `${xAt(index).toFixed(1)},${yAt(value).toFixed(1)}`).join(" ");
    const yValues = max >= 4 ? [0, Math.round(max / 2), max] : [...new Set([0, max])];
    const xIndexes = [...new Set([0, Math.floor((count - 1) / 2), count - 1])].filter((i) => i >= 0);
    return {
        created: toPoints(created),
        resolved: toPoints(resolved),
        createdTotal: created.at(-1) || 0,
        resolvedTotal: resolved.at(-1) || 0,
        width: CHART_W,
        height: CHART_H,
        left: LEFT,
        right: CHART_W - RIGHT,
        top: TOP,
        bottom: TOP + plotH,
        yTicks: yValues.map((value) => ({ y: Number(yAt(value).toFixed(1)), label: String(value) })),
        xTicks: xIndexes.map((index) => ({
            x: Number(xAt(index).toFixed(1)),
            label: dayLabel(flow.days[index]),
            anchor: index === 0 ? "start" : index === count - 1 ? "end" : "middle",
        })),
        days: flow.days.map((day, index) => ({
            x: Number(xAt(index).toFixed(1)),
            band: Math.max(step, 6),
            label: dayLabel(day),
            created: created[index],
            resolved: resolved[index],
            createdY: Number(yAt(created[index]).toFixed(1)),
            resolvedY: Number(yAt(resolved[index]).toFixed(1)),
        })),
    };
}

/** Width in percent of a bar against the biggest value, never below 2 when there is something. */
export function barWidth(value, max) {
    if (!value || !max) {
        return 0;
    }
    return Math.max(2, Math.round((value / max) * 100));
}

/** "12 min ago", "3 h ago", "yesterday" style text without a library. */
export function ago(isoDateTime, now = Date.now()) {
    const then = new Date(isoDateTime.replace(" ", "T") + "Z").getTime();
    const minutes = Math.max(0, Math.round((now - then) / 60000));
    if (minutes < 60) {
        return minutes <= 1 ? "just now" : `${minutes} min ago`;
    }
    const hours = Math.round(minutes / 60);
    if (hours < 24) {
        return `${hours} h ago`;
    }
    const days = Math.round(hours / 24);
    return days === 1 ? "yesterday" : `${days} days ago`;
}
