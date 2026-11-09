import { _t } from "@web/core/l10n/translation";

/** Ctrl+K (Cmd+K on a Mac) opens the palette, whatever has the focus. */
export function isPaletteKey(ev) {
    return (
        !ev.defaultPrevented && (ev.ctrlKey || ev.metaKey) && !ev.altKey && !ev.shiftKey && ev.key?.toLowerCase() === "k"
    );
}

/** Actions that are not screens; each names the method of the palette that runs it. */
export const PALETTE_ACTIONS = [{ key: "shortcuts", label: _t("Keyboard shortcuts") }];

/** The screens and actions whose name contains what was typed; everything when nothing was typed. */
export function matchTargets(targets, term) {
    const needle = (term || "").trim().toLowerCase();
    return targets.filter((target) => !needle || String(target.label).toLowerCase().includes(needle));
}

/** Sections for the list: [{ title, items }], without empty ones, and the same items flattened in order. */
export function buildSections({ issues, issuesTitle, screens, actions, projectId }) {
    // Issues of the open project first; the others, named by their project, in a group of their own.
    const here = projectId ? issues.filter((issue) => issue.project_id === projectId || !issue.project_id) : issues;
    const elsewhere = projectId ? issues.filter((issue) => issue.project_id && issue.project_id !== projectId) : [];
    const sections = [
        { title: issuesTitle, items: here.map((issue) => ({ type: "issue", issue })) },
        { title: _t("In other projects"), items: elsewhere.map((issue) => ({ type: "issue", issue })) },
        { title: _t("Go to"), items: screens.map((screen) => ({ type: "screen", screen })) },
        { title: _t("Actions"), items: actions.map((action) => ({ type: "action", action })) },
    ].filter((section) => section.items.length);
    const flat = sections.flatMap((section) => section.items);
    flat.forEach((item, index) => (item.index = index)); // the template highlights and keys rows by position
    return { sections, flat };
}

/** Move the highlighted row by one, wrapping at both ends. */
export function moveIndex(index, delta, count) {
    return count ? (index + delta + count) % count : 0;
}
