import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { isIOS, isDisplayStandalone } from "@web/core/browser/feature_detection";
import { browser } from "@web/core/browser/browser";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { pushState } from "./push_helpers";

/** "Phone notifications" in My notifications: allow this device to be told when Agile is not open. */
export class AgilePushSwitch extends Component {
    static template = "agile_community.PushSwitch";
    static props = { ...standardFieldProps };

    setup() {
        this.permission = useService("mail.notification.permission");
        this.state = useState({ asked: false });
    }

    get info() {
        return pushState({
            canNotify: Boolean(browser.Notification),
            isIOS: isIOS(),
            standalone: isDisplayStandalone(),
            permission: this.permission.permission,
            inboxOk: this.props.record.data[this.props.name],
        });
    }

    async turnOn() {
        this.state.asked = true;
        await this.permission.requestPermission();
    }
}

registry.category("fields").add("agile_push_switch", {
    component: AgilePushSwitch,
    supportedTypes: ["boolean"],
});
