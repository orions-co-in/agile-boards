import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";
import { deserializeDate, serializeDate } from "@web/core/l10n/dates";
import { calendarView } from "@web/views/calendar/calendar_view";
import { CalendarModel } from "@web/views/calendar/calendar_model";
import { CalendarController } from "@web/views/calendar/calendar_controller";
import { CalendarCommonRenderer } from "@web/views/calendar/calendar_common/calendar_common_renderer";

/** Palette slots of the calendar view: sprints and releases get their own, apart from the issues' stage colours. */
const SPAN_COLOR = { sprint: 6, release: 10 };

/**
 * The Calendar of the backlog: issues stay on their due dates; the project's sprints
 * (start to end) and releases (target date) are added as read-only all-day spans.
 */
export class AgileCalendarModel extends CalendarModel {
    get projectId() {
        const context = this.meta.context || {};
        return context.default_project_id || context.active_id || false;
    }

    async loadRecords(data) {
        const records = await super.loadRecords(data);
        if (!this.projectId) {
            return records;
        }
        let spans = [];
        try {
            spans = await this.orm.call("project.project", "agile_calendar_spans", [[this.projectId]], {
                start: serializeDate(data.range.start),
                end: serializeDate(data.range.end),
            });
        } catch {
            // The issues' due dates must still show when the spans cannot load.
            return records;
        }
        for (const span of spans) {
            records[span.id] = this.spanRecord(span);
        }
        return records;
    }

    spanRecord(span) {
        const start = deserializeDate(span.start).startOf("day");
        const end = deserializeDate(span.end).startOf("day");
        return {
            id: span.id,
            title: span.title,
            isAllDay: true,
            start,
            startType: "date",
            end,
            endType: "date",
            duration: 1,
            colorIndex: SPAN_COLOR[span.kind],
            isHatched: false,
            isStriked: false,
            isTimeHidden: true,
            isMonth: this.meta.scale === "month",
            isSmall: window.matchMedia("(max-width: 767.98px)").matches,
            agileSpan: span,
            rawRecord: span,
        };
    }

    /** Spans are read-only: dragging or resizing one must never write to a sprint or release. */
    async updateRecord(record, options = {}) {
        if (String(record.id).includes("-")) {
            return this.load();
        }
        return super.updateRecord(record, options);
    }
}

export class AgileCalendarController extends CalendarController {
    /** A span opens its own form, not the issue form. */
    async editRecord(record, context = {}) {
        const span = record?.agileSpan;
        if (!span) {
            return super.editRecord(record, context);
        }
        return this.action.doAction({
            type: "ir.actions.act_window",
            name: span.title,
            res_model: span.res_model,
            res_id: span.res_id,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("views").add("agile_calendar", {
    ...calendarView,
    Model: AgileCalendarModel,
    Controller: AgileCalendarController,
});

// The common renderer is shared by every calendar; each patch only acts on records carrying agileSpan.
patch(CalendarCommonRenderer.prototype, {
    onClick(info) {
        const record = this.props.model.records[info.event.id];
        if (record?.agileSpan) {
            return this.props.editRecord(record);
        }
        return super.onClick(info);
    },
    convertRecordToEvent(record) {
        const event = super.convertRecordToEvent(record);
        return record.agileSpan ? { ...event, editable: false } : event;
    },
    eventClassNames(arg) {
        const classes = super.eventClassNames(arg);
        const record = this.props.model.records[arg.event.id];
        if (record?.agileSpan) {
            classes.push("o_ag_cal_span", `o_ag_cal_${record.agileSpan.kind}`);
        }
        return classes;
    },
});
