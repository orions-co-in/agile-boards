/** Pure helpers for the workflow canvas (C-801 to C-804). Records come from the form's own lists. */

const ROLE_FIELDS = [
    ["allow_contributor", "Contributors"],
    ["allow_reviewer", "Reviewers"],
    ["allow_manager", "Managers"],
];

const CONDITION_FIELDS = [
    ["require_no_open_subtasks", "all sub-issues done or canceled"],
    ["require_not_blocked", "the issue not blocked"],
];

/** One line for an action of a move, as the panel lists it. */
export function actionText(data) {
    if (data.action_type === "set_field") {
        const labels = { 0: "Low", 1: "Medium", 2: "High", 3: "Urgent" };
        return `Set priority to ${labels[data.set_priority] || ""}`.trim();
    }
    if (data.action_type === "assign") {
        const user = data.assign_user_id;
        return `Assign to ${user?.display_name || user?.[1] || ""}`.trim();
    }
    if (data.action_type === "notify") {
        return `Message the assignees: ${data.message || ""}`.trim();
    }
    return `Add a comment: ${data.message || ""}`.trim();
}

/** The id a list record is known by: its database id, or the virtual id of an unsaved line. */
export function recordKey(record) {
    return record.resId || record._virtualId;
}

/**
 * The picture's data, read straight from the Statuses and Moves lists so the canvas always shows
 * what the lists hold (including lines not saved yet). Each item keeps its record for editing.
 */
export function buildModel(statusRecords, moveRecords) {
    const statuses = [...statusRecords]
        .sort((a, b) => (a.data.sequence - b.data.sequence) || (recordKey(a) - recordKey(b)))
        .map((record) => ({
            stage_id: recordKey(record),
            name: record.data.name || record.data.stage_id?.display_name || record.data.stage_id?.[1] || "",
            category: record.data.category,
            count: record.data.issue_count || 0,
            hidden: record.data.stage_active === false,
            canDelete: Boolean(record.data.can_delete),
            record,
        }));
    const moves = moveRecords
        .filter((record) => record.data.from_status_id && record.data.to_status_id)
        .map((record) => ({
            id: recordKey(record),
            name: record.data.name || "",
            from: record.data.from_status_id.id ?? record.data.from_status_id[0],
            to: record.data.to_status_id.id ?? record.data.to_status_id[0],
            roles: ROLE_FIELDS.filter(([field]) => record.data[field]).map(([, label]) => label),
            conditions: [
                ...CONDITION_FIELDS.filter(([field]) => record.data[field]).map(([, label]) => label),
                ...(record.data.required_custom_field_ids?.records || []).map(
                    (field) => field.data.display_name || field.data.name || ""
                ),
            ],
            actions: (record.data.action_ids?.records || []).map((rule) => ({ record: rule, text: actionText(rule.data) })),
            record,
        }));
    return { statuses, moves };
}

/** The status keys in their new order after one is dragged to a position (0 based). */
export function reorder(keys, key, target) {
    const from = keys.indexOf(key);
    if (from < 0) {
        return keys;
    }
    const next = keys.filter((k) => k !== key);
    next.splice(Math.max(0, Math.min(target, next.length)), 0, key);
    return next;
}

/** Sequence numbers for an order: 10, 20, 30 ... so later inserts still fit. */
export function sequencesFor(keys) {
    return Object.fromEntries(keys.map((key, index) => [key, (index + 1) * 10]));
}

/** Whether a move between the two statuses already exists (a pair has one move). */
export function hasMove(moves, from, to) {
    return moves.some((move) => move.from === from && move.to === to);
}
