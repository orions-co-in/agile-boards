/**
 * What the "Phone notifications" line says and offers, from what the browser can do.
 * Odoo's web client subscribes the device by itself once the browser permission is granted,
 * so the only step left to a person is to allow notifications.
 */
export function pushState({ canNotify, isIOS, standalone, permission, inboxOk }) {
    if (isIOS && !standalone) {
        return {
            kind: "needs_install",
            text: "On an iPhone, add Agile to the Home Screen first (Install app in the sidebar), then open it from there and turn this on.",
        };
    }
    if (!canNotify) {
        return { kind: "unsupported", text: "This browser cannot receive phone notifications." };
    }
    if (permission === "denied") {
        return {
            kind: "blocked",
            text: "Notifications are blocked for this site. Allow them in the browser settings, then come back here.",
        };
    }
    if (permission === "granted") {
        return {
            kind: inboxOk ? "on" : "on_but_email",
            text: inboxOk
                ? "Phone notifications are on for this device. Assignment, mention and status messages arrive when Agile is not open."
                : "Phone notifications are allowed on this device, but your Odoo preference is By Emails. Change it to In Odoo in your preferences to get status messages.",
        };
    }
    return { kind: "off", text: "Phone notifications are off for this device." };
}
