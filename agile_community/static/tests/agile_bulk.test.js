import { describe, expect, test } from "@odoo/hoot";
import { makeMockEnv } from "@web/../tests/web_test_helpers";
import { resultText } from "@agile_community/bulk/agile_bulk_bar";

describe.current.tags("desktop");

test("the result line says how many changed, what happened and how many were refused", async () => {
    await makeMockEnv();
    expect(resultText("sprint", "Sprint 3", 5, 5, 0)).toBe("5 of 5 issues moved to Sprint 3.");
    expect(resultText("sprint", "Sprint 3", 4, 5, 1)).toBe("4 of 5 issues moved to Sprint 3. 1 was refused.");
    expect(resultText("status", "Done", 1, 4, 3)).toBe("1 of 4 issues moved to Done. 3 were refused.");
    expect(resultText("assignee", "Sam", 2, 2, 0)).toBe("2 of 2 issues assigned to Sam.");
    expect(resultText("assignee", "", 2, 2, 0)).toBe("2 of 2 issues unassigned.");
    expect(resultText("sprint", "", 3, 3, 0)).toBe("3 of 3 issues moved to the Backlog.");
    expect(resultText("label_add", "Urgent", 3, 3, 0)).toBe("3 of 3 issues labelled Urgent.");
    expect(resultText("label_remove", "Urgent", 3, 3, 0)).toBe("3 of 3 issues unlabelled Urgent.");
    expect(resultText("type", "Bug", 2, 2, 0)).toBe("2 of 2 issues set to the type Bug.");
    expect(resultText("priority", "High priority", 2, 3, 1)).toBe("2 of 3 issues set to High priority. 1 was refused.");
    expect(resultText("due", "2026-11-20", 2, 2, 0)).toBe("2 of 2 issues given the due date 2026-11-20.");
    expect(resultText("due", "", 2, 2, 0)).toBe("2 of 2 issues cleared of their due date.");
    expect(resultText("watch", "", 2, 2, 0)).toBe("2 of 2 issues added to your watch list.");
    expect(resultText("unwatch", "", 2, 2, 0)).toBe("2 of 2 issues removed from your watch list.");
});
