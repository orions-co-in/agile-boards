import { registry } from "@web/core/registry";
import { FloatField, floatField } from "@web/views/fields/float/float_field";

/**
 * Story points as the guide says: blank means not estimated, and 0 is a real estimate (NU-19).
 * The stored value of an issue nobody estimated is 0, so it shows empty until someone types a number.
 */
export class AgilePointsField extends FloatField {
    // The placeholder is passed by extractProps below; Owl's dev-mode prop check needs it declared.
    static props = { ...FloatField.props, placeholder: { type: String, optional: true } };

    get formattedValue() {
        const data = this.props.record.data;
        if (data.story_points_estimated === false && !this.value) {
            return "";
        }
        return super.formattedValue;
    }
}

registry.category("fields").add("agile_points", {
    ...floatField,
    component: AgilePointsField,
    extractProps(fieldInfo, dynamicInfo) {
        const props = floatField.extractProps(fieldInfo, dynamicInfo);
        props.placeholder = props.placeholder || fieldInfo.placeholder || "Not estimated";
        return props;
    },
});
