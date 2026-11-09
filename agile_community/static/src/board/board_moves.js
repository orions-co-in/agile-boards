import { _t } from "@web/core/l10n/translation";

/** Words for the moves on the board; the same text goes to the screen and to screen readers. */

export function movedMessage(key, stageName) {
    return _t("%(key)s moved to %(stage)s.", { key, stage: stageName });
}

/** The server said no (a workflow rule, a missing estimate...): the card stays where it was. */
export function refusedMessage(key, reason) {
    return reason
        ? _t("%(key)s was not moved. %(reason)s", { key, reason })
        : _t("%(key)s was not moved.", { key });
}

/** Dropping on another swimlane row would be a hidden edit, so it is refused. */
export function otherRowMessage(key, laneLabel, swimlane) {
    const what = {
        epic: _t("the epic"),
        priority: _t("the priority"),
        component: _t("the component"),
        label: _t("the labels"),
    }[swimlane] || (String(swimlane).startsWith("filter:") ? _t("what the filter matches") : _t("the assignee"));
    return _t("%(key)s stays in %(lane)s. Open the issue to change %(what)s.", { key, lane: laneLabel, what });
}

export function edgeMessage(key, direction) {
    return direction < 0
        ? _t("%(key)s is already in the first column.", { key })
        : _t("%(key)s is already in the last column.", { key });
}

/** The next open column to the left (-1) or right (+1), or null at the edge. */
export function neighbourGroup(groups, current, direction) {
    const open = groups.filter((group) => !group.isFolded);
    const index = open.indexOf(current);
    return index < 0 ? null : (open[index + direction] ?? null);
}

export function reasonOf(error) {
    return error?.data?.message || error?.message || "";
}
