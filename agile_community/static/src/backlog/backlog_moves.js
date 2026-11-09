import { _t } from "@web/core/l10n/translation";

/**
 * Wording for the results of moving an issue in the backlog (spec section 12).
 * A "location" is { name, sprint } where sprint is the header data of a sprint,
 * or null for the Backlog.
 */

export function rankMessage(key, position, total, groupName) {
    return _t("%(key)s is now %(position)s of %(total)s in %(group)s.", {
        key,
        position,
        total,
        group: groupName,
    });
}

export function boundaryMessage(key, edge, groupName) {
    return edge === "first"
        ? _t("%(key)s is already first in %(group)s.", { key, group: groupName })
        : _t("%(key)s is already last in %(group)s.", { key, group: groupName });
}

const isActive = (location) => location.sprint?.state === "in_progress";
const isConfirmedPlan = (location) =>
    location.sprint?.state === "draft" && location.sprint.planning_confirmed;

/** What a move did to the sprints involved, in plain words. */
export function moveMessage(key, from, to) {
    const parts = [];
    if (isActive(to)) {
        parts.push(
            _t("%(key)s added to %(name)s. It counts as a scope change on the Pulse.", {
                key,
                name: to.name,
            })
        );
    } else if (isConfirmedPlan(to)) {
        parts.push(
            _t("%(key)s added to %(name)s. The confirmed plan changed: update it before starting.", {
                key,
                name: to.name,
            })
        );
    } else {
        parts.push(_t("%(key)s moved to %(name)s.", { key, name: to.name }));
    }
    if (isActive(from)) {
        parts.push(_t("It counts as a scope change on the Pulse."));
    } else if (isConfirmedPlan(from)) {
        parts.push(
            _t("The confirmed plan of %(name)s changed: update it before starting.", { name: from.name })
        );
    }
    return parts.join(" ");
}

export function refusalMessage(key, reason) {
    return reason
        ? _t("Could not move %(key)s: %(reason)s", { key, reason })
        : _t("Could not move %(key)s.", { key });
}
