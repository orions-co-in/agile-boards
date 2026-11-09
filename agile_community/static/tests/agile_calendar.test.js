import { describe, expect, test } from "@odoo/hoot";
import { AgileCalendarModel } from "@agile_community/calendar/agile_calendar";

describe.current.tags("desktop");

const SPAN = { id: "sprint-3", kind: "sprint", res_model: "project.sprint", res_id: 3, title: "Sprint: S1", start: "2026-11-02", end: "2026-11-15" };

function fakeModel(overrides = {}) {
    const model = Object.create(AgileCalendarModel.prototype);
    model.meta = { scale: "month", context: { default_project_id: 7 } };
    model.env = { isSmall: false };
    return Object.assign(model, overrides);
}

test("a sprint or release becomes a read-only all-day record that keeps its source", () => {
    const record = fakeModel().spanRecord(SPAN);
    expect(record.id).toBe("sprint-3");
    expect(record.isAllDay).toBe(true);
    expect(record.title).toBe("Sprint: S1");
    expect(record.start.toISODate()).toBe("2026-11-02");
    expect(record.end.toISODate()).toBe("2026-11-15");
    expect(record.agileSpan.res_id).toBe(3);
});

test("sprints and releases use different colours", () => {
    const model = fakeModel();
    const sprint = model.spanRecord(SPAN);
    const release = model.spanRecord({ ...SPAN, id: "release-1", kind: "release" });
    expect(sprint.colorIndex).not.toBe(release.colorIndex);
});

test("the project comes from the action context", () => {
    expect(fakeModel().projectId).toBe(7);
    expect(fakeModel({ meta: { context: { active_id: 9 } } }).projectId).toBe(9);
    expect(fakeModel({ meta: { context: {} } }).projectId).toBe(false);
});

test("moving a span never writes; it reloads the calendar", async () => {
    let loads = 0;
    const model = fakeModel({ load: async () => { loads++; } });
    await model.updateRecord({ id: "sprint-3" });
    expect(loads).toBe(1);
});
