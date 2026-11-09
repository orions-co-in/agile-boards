import { _t } from "@web/core/l10n/translation";

/**
 * The WIP badge of a column: how full the stage is, always in words.
 * WIP is a warning, not a cap, so "over" is a state of the badge and nothing blocks.
 */
export function wipState(limit, current) {
    if (!limit) {
        return null;
    }
    if (current > limit) {
        return {
            kind: "over",
            icon: "▲",
            text: _t("WIP %(current)s of %(limit)s, over by %(over)s", { current, limit, over: current - limit }),
        };
    }
    if (current === limit) {
        return { kind: "at", icon: "●", text: _t("WIP %(current)s of %(limit)s, at the limit", { current, limit }) };
    }
    return { kind: "ok", icon: "", text: _t("WIP %(current)s of %(limit)s", { current, limit }) };
}

/** Blocked cards among the loaded records of a column. */
export function blockedCount(records) {
    return records.filter((record) => record.data.agile_is_blocked).length;
}

/** Column facts the header and the swimlane headings share. */
export function columnFacts(group, wipByStage, swimlaneMode = false) {
    const stageId = Array.isArray(group.value) ? group.value[0] : group.value;
    const entry = wipByStage?.[stageId];
    // A per-row limit has no whole-column count while swimlanes show; each row counts its own cards.
    const perRow = entry?.per_swimlane && swimlaneMode;
    return {
        wip: !entry
            ? null
            : perRow
              ? { kind: "row", icon: "", text: _t("WIP limit %(limit)s in each row", { limit: entry.limit }) }
              : wipState(entry.limit, entry.current),
        // Odoo fills an empty board with sample cards; their blocked flags are not real (NU-30).
        blocked: group.model?.useSampleModel ? 0 : blockedCount(group.list.records),
    };
}

/** The WIP badge of one swimlane cell, or null when the stage has no per-row limit. */
export function cellWip(group, wipByStage, count) {
    const stageId = Array.isArray(group.value) ? group.value[0] : group.value;
    const entry = wipByStage?.[stageId];
    return entry?.per_swimlane ? wipState(entry.limit, count) : null;
}

/** Message for a card dropped into a column that is now over its limit. */
export function overLimitMessage(issueKey, stageName, wip) {
    return _t("%(key)s moved to %(stage)s. %(wip)s. This is a warning, not a limit.", {
        key: issueKey,
        stage: stageName,
        wip: wip.text,
    });
}

/** Where the folded swimlane rows are remembered: per project and kind of swimlane, in this browser. */
export function lanesKey(projectId, swimlane) {
    return `agile_board_lanes_closed:${projectId}:${swimlane}`;
}

export function readClosedLanes(storage, key) {
    try {
        const value = JSON.parse(storage.getItem(key));
        return Array.isArray(value) ? value.filter((entry) => typeof entry === "string") : [];
    } catch {
        // Storage can be blocked or hold something else; rows then simply start open.
        return [];
    }
}

export function writeClosedLanes(storage, key, closed) {
    try {
        if (closed.length) {
            storage.setItem(key, JSON.stringify(closed));
        } else {
            storage.removeItem(key);
        }
    } catch {
        // A convenience only.
    }
}
