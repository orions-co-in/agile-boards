import { _t } from "@web/core/l10n/translation";

/** The shortcuts, as the help dialog lists them (S-932). */
export const SHORTCUTS = [
    { keys: "c", label: _t("Create an issue"), where: _t("Backlog (the add line of the first section) and Board (New)") },
    { keys: "/", label: _t("Search"), where: _t("Backlog, Board and lists") },
    { keys: "m", label: _t("Move the focused issue"), where: _t("Backlog row or Board card") },
    { keys: "Ctrl + K", label: _t("Go to an issue, a recent issue or a screen"), where: _t("Every project screen (Cmd + K on a Mac)") },
    { keys: "?", label: _t("Show this list"), where: _t("Every project screen") },
    { keys: "Alt + Up, Alt + Down", label: _t("Rank the focused Backlog row"), where: _t("Backlog") },
];

/** True while the person is typing: a field, a select, or an editable area. */
export function isTypingTarget(el) {
    if (!el || !el.tagName) {
        return false;
    }
    if (["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName)) {
        return true;
    }
    return Boolean(el.isContentEditable || el.closest?.("[contenteditable=''], [contenteditable='true']"));
}

/**
 * Which shortcut a key press asks for, or null. Plain keys only (Ctrl, Cmd and Alt belong to the
 * browser and to Backlog ranking), never while typing, never for a held key.
 */
export function shortcutFor(ev) {
    if (ev.defaultPrevented || ev.repeat || ev.ctrlKey || ev.metaKey || ev.altKey || isTypingTarget(ev.target)) {
        return null;
    }
    if (ev.key === "?") {
        return "help";
    }
    if (ev.shiftKey) {
        return null;
    }
    return { c: "create", "/": "search", m: "move" }[ev.key] || null;
}
