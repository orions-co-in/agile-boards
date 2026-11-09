import { _t } from "@web/core/l10n/translation";

/** The word for a project's estimate unit, as it reads after a number: "8 points", "8 hours", "8 issues". */
export function unitWord(unit) {
    return { hours: _t("hours"), issues: _t("issues") }[unit] || _t("points");
}

/** Short form for tight spots such as a pill: "8 pts", "8 h", "8 issues". */
export function unitShort(unit) {
    return { hours: _t("h"), issues: _t("issues") }[unit] || _t("pts");
}
