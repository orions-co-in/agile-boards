// Pure helpers of the Dashboards page (L-1042). Tiles keep an order and one of three widths.
export const WIDTHS = [1, 2, 3];

export function widthLabel(width) {
    return { 1: "Small", 2: "Medium", 3: "Full" }[width] || "Small";
}

export function nextWidth(width) {
    return (width % WIDTHS.length) + 1;
}

/** A new array with the tile moved one place (delta -1 or +1); same array content when it cannot move. */
export function moveBy(tiles, id, delta) {
    const from = tiles.findIndex((tile) => tile.id === id);
    const to = from + delta;
    if (from < 0 || to < 0 || to >= tiles.length) {
        return tiles.slice();
    }
    const next = tiles.slice();
    [next[from], next[to]] = [next[to], next[from]];
    return next;
}

/** Move a tile so it lands before position `at` of the list as it was before the move. */
export function moveTo(tiles, id, at) {
    const from = tiles.findIndex((tile) => tile.id === id);
    if (from < 0) {
        return tiles.slice();
    }
    const next = tiles.slice();
    const [tile] = next.splice(from, 1);
    next.splice(at > from ? at - 1 : at, 0, tile);
    return next;
}

/**
 * Where a dragged tile would land: the index of the first tile whose middle is below the pointer
 * in its row (rects are the grid tiles' boxes in order, the dragged one excluded by the caller).
 */
export function dropIndex(rects, x, y) {
    for (let index = 0; index < rects.length; index++) {
        const rect = rects[index];
        if (y < rect.top + rect.height / 2 && x < rect.right) {
            return index;
        }
    }
    return rects.length;
}

/** The body the layout call sends: every tile once, in order, with its width. */
export function layoutItems(tiles) {
    return tiles.map((tile) => ({ id: tile.id, width: tile.width }));
}

export function dueLabel(due) {
    if (!due) {
        return "";
    }
    return due.slice(0, 10);
}

export function seriesMax(series) {
    const values = series.flatMap((row) => row.values).filter((value) => value !== null && value !== false);
    return Math.max(1, ...values);
}

/** Width of a bar in percent of the longest one; a value above zero is never thinner than 2%. */
export function barPercent(value, max) {
    if (!value || !max) {
        return 0;
    }
    return Math.max(2, Math.round((value / max) * 100));
}

/**
 * The points of each unbroken run of a line chart, as SVG "x,y" strings; a missing value
 * (a day that has not happened yet) ends the run. The line fills the width, 0 at the bottom.
 */
export function lineSegments(values, max, width, height, pad = 4) {
    const step = values.length > 1 ? (width - 2 * pad) / (values.length - 1) : 0;
    const runs = [];
    let run = [];
    values.forEach((value, index) => {
        if (value === null || value === false || value === undefined) {
            if (run.length) {
                runs.push(run.join(" "));
            }
            run = [];
            return;
        }
        const x = pad + index * step;
        const y = height - pad - (value / max) * (height - 2 * pad);
        run.push(`${x.toFixed(1)},${y.toFixed(1)}`);
    });
    if (run.length) {
        runs.push(run.join(" "));
    }
    return runs;
}

/** The share of the committed points that are done, as a whole percent from 0 to 100. */
export function donePercent(done, committed) {
    if (!committed) {
        return 0;
    }
    return Math.min(100, Math.max(0, Math.round((done / committed) * 100)));
}

export const WALL_INTERVALS = [30, 60, 300];
const WALL_KEY = "agile_community.wallboard.interval";

/** Seconds between refreshes on the wallboard: the stored choice when it is one of the offered ones, else 60. */
export function readWallInterval(storage) {
    try {
        const value = Number(storage.getItem(WALL_KEY));
        return WALL_INTERVALS.includes(value) ? value : 60;
    } catch {
        return 60;
    }
}

/** Remember the choice; blocked storage is ignored. */
export function writeWallInterval(storage, seconds) {
    try {
        storage.setItem(WALL_KEY, String(seconds));
    } catch {
        // storage is a convenience only
    }
}

/** "30 seconds", "1 minute", "5 minutes" for an interval. */
export function wallIntervalLabel(seconds) {
    if (seconds < 60) {
        return `${seconds} seconds`;
    }
    const minutes = seconds / 60;
    return minutes === 1 ? "1 minute" : `${minutes} minutes`;
}

/** The time of day of a timestamp, as hours and minutes in the browser's language. */
export function clockText(timestamp) {
    return new Date(timestamp).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}
