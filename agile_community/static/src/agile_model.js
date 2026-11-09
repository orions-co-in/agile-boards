import { Component } from "@odoo/owl";

/**
 * Owl 3's t-model binds to a function with a `set` method (a signal). Agile
 * keeps form state in reactive proxies, so templates bind through this helper:
 * `t-model="this.agileModel(this.state, 'title')"`.
 */
function agileModel(object, key) {
    const accessor = () => object[key];
    accessor.set = (value) => {
        object[key] = value;
    };
    return accessor;
}

for (let proto = Component.prototype; proto && proto !== Object.prototype; proto = Object.getPrototypeOf(proto)) {
    if (Object.hasOwn(proto, "setup") || proto === Component.prototype) {
        proto.agileModel = agileModel;
        break;
    }
}
Component.prototype.agileModel = agileModel;
