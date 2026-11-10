import { describe, expect, test } from "@odoo/hoot";
import { click, edit, queryAllTexts, queryOne, select } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { makeTestApp, mountWithCleanup, onRpc } from "@web/../tests/web_test_helpers";
import { Component, proxy, xml, useProps, t } from "@odoo/owl";
import { AgileBoardBar } from "@agile_community/board/agile_board_bar";
import { buildLanes, laneFilterId, mergeColumns } from "@agile_community/board/agile_board_renderer";

describe.current.tags("desktop");

defineMailModels();

const OPTIONS = {
    project_id: 7,
    swimlane: "none",
    filters: [],
    task_types: [{ id: 3, name: "Bug" }, { id: 4, name: "Story" }],
    epics: [{ id: 12, name: "Search", issue_key: "WALK-12" }],
};

/** A tiny stand-in for the search model: filters with an active flag. */
function fakeSearchModel() {
    let nextId = 100;
    const items = [
        { id: 1, type: "filter", name: "agile_quick_my_issues", isActive: false },
        { id: 2, type: "filter", name: "agile_blocked", isActive: false },
    ];
    return {
        items,
        getSearchItems(predicate) {
            return this.items.filter(predicate);
        },
        toggleSearchItem(id) {
            const item = this.items.find((entry) => entry.id === id);
            item.isActive = !item.isActive;
        },
        createNewFilters(filters) {
            for (const filter of filters) {
                this.items.push({ id: nextId++, type: "filter", isActive: true, ...filter });
            }
        },
    };
}

class Host extends Component {
    static components = { AgileBoardBar };
    props = useProps({ searchModel: t.any() });
    static template = xml`<AgileBoardBar projectId="7" filterKey="this.key" swimlane="this.state.swimlane" onSwimlane="(value) => this.state.swimlane = value"/>`;

    setup() {
        this.state = proxy({ swimlane: "none" });
        this.model = proxy(this.props.searchModel);
    }

    get key() {
        return this.model.items.map((item) => `${item.id}:${item.isActive ? 1 : 0}`).join(",");
    }
}

async function mountBar({ options = OPTIONS, fail = false } = {}) {
    const searchModel = proxy(fakeSearchModel());
    const saves = [];
    onRpc("project.project", "agile_board_options", () => {
        if (fail) {
            throw new Error("nope");
        }
        return options;
    });
    onRpc("project.project", "agile_save_board_options", ({ kwargs }) => {
        saves.push({ swimlane: kwargs.swimlane, filters: kwargs.filters });
        return true;
    });
    await makeTestApp();
    const host = await mountWithCleanup(Host, { props: { searchModel }, componentEnv: { searchModel } });
    await animationFrame();
    return { searchModel, saves, host };
}

const pressed = () =>
    queryAllTexts("[data-chip][aria-pressed=true]");

test("the bar offers Mine, Blocked, type and epic pick lists and the swimlane choice", async () => {
    await mountBar();
    expect(queryAllTexts("[data-chip]")).toEqual(["Mine", "Blocked", "Flagged"]);
    expect(queryAllTexts("[data-pick=type] option")).toEqual(["All types", "Bug", "Story"]);
    expect(queryAllTexts("[data-pick=epic] option")).toEqual(["All epics", "WALK-12 Search"]);
    expect(queryAllTexts("[data-pick=swimlane] option")).toEqual(["None", "Assignee", "Epic", "Priority", "Component", "Label"]);
    expect(queryOne("[data-pick=swimlane]").value).toBe("none");
    expect(pressed()).toEqual([]);
});

test("a chip switches its filter on and off", async () => {
    const { searchModel } = await mountBar();
    await click("[data-chip=mine]");
    await animationFrame();
    expect(searchModel.items[0].isActive).toBe(true);
    expect(pressed()).toEqual(["Mine"]);
    expect(queryOne("[data-pick=swimlane]").value).toBe("none");
    await click("[data-chip=mine]");
    await animationFrame();
    expect(searchModel.items[0].isActive).toBe(false);
});

test("choosing a type or an epic adds one removable filter and a new choice replaces it", async () => {
    const { searchModel } = await mountBar();
    queryOne("[data-pick=type]").value = "3";
    queryOne("[data-pick=type]").dispatchEvent(new Event("change", { bubbles: true }));
    await animationFrame();
    let types = searchModel.items.filter((item) => item.agileBoardKey?.startsWith("type:"));
    expect(types.map((item) => [item.agileBoardKey, item.isActive])).toEqual([["type:3", true]]);
    expect(types[0].domain).toBe('[("agile_task_type_id", "=", 3)]');
    queryOne("[data-pick=type]").value = "4";
    queryOne("[data-pick=type]").dispatchEvent(new Event("change", { bubbles: true }));
    await animationFrame();
    types = searchModel.items.filter((item) => item.agileBoardKey?.startsWith("type:"));
    expect(types.map((item) => [item.agileBoardKey, item.isActive])).toEqual([
        ["type:3", false],
        ["type:4", true],
    ]);
    queryOne("[data-pick=type]").value = "";
    queryOne("[data-pick=type]").dispatchEvent(new Event("change", { bubbles: true }));
    await animationFrame();
    expect(searchModel.items.filter((item) => item.agileBoardKey && item.isActive)).toHaveLength(0);
    const epic = queryOne("[data-pick=epic]");
    epic.value = "12";
    epic.dispatchEvent(new Event("change", { bubbles: true }));
    await animationFrame();
    expect(searchModel.items.find((item) => item.agileBoardKey === "epic:12").domain).toBe(
        '[("parent_id", "=", 12)]'
    );
});

test("filters saved for this person are applied when the board opens", async () => {
    const { searchModel } = await mountBar({
        options: { ...OPTIONS, filters: ["blocked", "epic:12", "type:99"], swimlane: "epic" },
    });
    expect(searchModel.items[1].isActive).toBe(true);
    expect(searchModel.items.some((item) => item.agileBoardKey === "epic:12" && item.isActive)).toBe(true);
    // A type that no longer exists is skipped rather than failing.
    expect(searchModel.items.some((item) => item.agileBoardKey === "type:99")).toBe(false);
    expect(pressed()).toEqual(["Blocked"]);
    expect(queryOne("[data-pick=swimlane]").value).toBe("epic");
});

test("changing a chip saves the new set; opening the board does not save", async () => {
    const { saves } = await mountBar({ options: { ...OPTIONS, filters: ["mine"] } });
    expect(saves).toEqual([]);
    await click("[data-chip=blocked]");
    await animationFrame();
    await animationFrame();
    expect(saves.at(-1)).toEqual({ swimlane: undefined, filters: ["mine", "blocked"] });
});

test("choosing a swimlane saves it once and tells the board", async () => {
    const { saves } = await mountBar();
    await select("assignee", { target: "[data-pick=swimlane]" });
    await animationFrame();
    expect(queryOne("[data-pick=swimlane]").value).toBe("assignee");
    expect(saves).toEqual([{ swimlane: "assignee", filters: undefined }]);
    await select("assignee", { target: "[data-pick=swimlane]" });
    await animationFrame();
    expect(saves).toHaveLength(1);
});

test("when the pick lists cannot load, Mine and Blocked still work", async () => {
    const { searchModel } = await mountBar({ fail: true });
    expect(queryAllTexts("[data-chip]")).toEqual(["Mine", "Blocked", "Flagged"]);
    // Only the swimlane choice stays: it needs nothing from the server.
    expect("[data-pick]:not([data-pick=swimlane])").toHaveCount(0);
    await click("[data-chip=blocked]");
    await animationFrame();
    expect(searchModel.items[1].isActive).toBe(true);
});

test("lanes group issues by assignee, name first and Unassigned last, with counts and points", () => {
    const rec = (id, lane, points, estimated = true) => ({
        id,
        data: { agile_lane_assignee: lane, agile_lane_epic: "", story_points: points, story_points_estimated: estimated },
    });
    const groups = [
        { id: "backlog", list: { records: [rec(1, "Zed", 3), rec(2, "", 2), rec(3, "Amy", 5)] } },
        { id: "done", list: { records: [rec(4, "Amy", 1), rec(5, "Amy", 8, false)] } },
    ];
    const lanes = buildLanes(groups, "assignee", "Unassigned");
    expect(lanes.map((lane) => lane.label)).toEqual(["Amy", "Zed", "Unassigned"]);
    const amy = lanes[0];
    expect(amy.count).toBe(3);
    expect(amy.points).toBe(6);
    expect(amy.cells.map((cell) => cell.records.map((record) => record.id))).toEqual([[3], [4, 5]]);
    expect(lanes[2].cells.map((cell) => cell.records.length)).toEqual([1, 0]);
});

test("lanes by epic use the epic label", () => {
    const groups = [
        {
            id: "g",
            list: {
                records: [
                    { id: 1, data: { agile_lane_epic: "WALK-12 Search", agile_lane_assignee: "x", story_points_estimated: false } },
                    { id: 2, data: { agile_lane_epic: "", agile_lane_assignee: "x", story_points_estimated: false } },
                ],
            },
        },
    ];
    expect(buildLanes(groups, "epic", "No epic").map((lane) => lane.label)).toEqual(["WALK-12 Search", "No epic"]);
});

test("the Sprint pick list shows only when several sprints are active and filters by the chosen one", async () => {
    await mountBar();
    expect("[data-pick=sprint]").toHaveCount(0);
});

test("with several active sprints the bar lets you tick sprints; the default is all of them", async () => {
    const options = { ...OPTIONS, sprints: [{ id: 1, name: "Sprint A" }, { id: 2, name: "Sprint B" }] };
    const { searchModel } = await mountBar({ options });
    expect("[data-pick=sprint]").toHaveText("All active sprints");
    await click("[data-pick=sprint]");
    await animationFrame();
    expect(queryAllTexts(".o_ag_multi_row")).toEqual(["Sprint A", "Sprint B"]);
    await click(".o_ag_multi_row:eq(1) input");
    await animationFrame();
    let item = searchModel.items.find((entry) => entry.agileBoardKeys);
    expect(item.agileBoardKeys).toEqual(["sprint:2"]);
    expect(item.domain).toBe('[["sprint_id","in",[2]]]');
    expect("[data-pick=sprint]").toHaveText("Sprint B");
    await click(".o_ag_multi_row:eq(0) input");
    await animationFrame();
    item = searchModel.items.find((entry) => entry.isActive && entry.agileBoardKeys);
    expect(item.agileBoardKeys).toEqual(["sprint:2", "sprint:1"]);
    expect(item.domain).toBe('[["sprint_id","in",[2,1]]]');
    expect("[data-pick=sprint]").toHaveText("2 sprints");
});

test("choosing a saved view switches the chips, the pick lists and the swimlane", async () => {
    const options = { ...OPTIONS, views: [{ name: "My work", filters: ["mine", "type:3"], swimlane: "assignee" }] };
    const { searchModel } = await mountBar({ options });
    await click(".o_ag_views_btn");
    await animationFrame();
    expect(queryAllTexts(".o_ag_view_apply")).toEqual(["My work"]);
    await click(".o_ag_view_apply");
    await animationFrame();
    expect(searchModel.items[0].isActive).toBe(true);
    expect(searchModel.items.find((item) => item.agileBoardKey === "type:3").isActive).toBe(true);
    expect(pressed()).toEqual(["Mine"]);
    expect(queryOne("[data-pick=swimlane]").value).toBe("assignee");
});

test("a view replaces what was on before it, and saving sends the current filters and swimlane", async () => {
    const saved = [];
    onRpc("project.project", "agile_save_board_view", ({ kwargs }) => {
        saved.push({ name: kwargs.name, filters: kwargs.filters, swimlane: kwargs.swimlane });
        return [{ name: kwargs.name, filters: kwargs.filters, swimlane: kwargs.swimlane }];
    });
    const options = { ...OPTIONS, views: [{ name: "Only blocked", filters: ["blocked"], swimlane: "none" }] };
    const { searchModel } = await mountBar({ options });
    await click("[data-chip=mine]");
    await animationFrame();
    await click(".o_ag_views_btn");
    await animationFrame();
    await click(".o_ag_view_apply");
    await animationFrame();
    expect(searchModel.items[0].isActive).toBe(false);
    expect(searchModel.items[1].isActive).toBe(true);
    await click(".o_ag_views_btn");
    await animationFrame();
    await click(".o_ag_view_save");
    await animationFrame();
    await click(".o_ag_view_name");
    await edit("Triage");
    await click(".o_ag_view_confirm");
    await animationFrame();
    expect(saved).toEqual([{ name: "Triage", filters: ["blocked"], swimlane: "none" }]);
});

test("lanes by priority, component and label use their own field; a saved filter makes two rows", () => {
    const rec = (id, extra) => ({
        id,
        resId: id,
        data: { agile_lane_priority: "", agile_lane_component: "", agile_lane_label: "", story_points_estimated: false, ...extra },
    });
    const groups = [{ id: "g", list: { records: [rec(1, { agile_lane_priority: "High" }), rec(2, {})] } }];
    expect(buildLanes(groups, "priority", "No priority").map((lane) => lane.label)).toEqual(["High", "No priority"]);
    const byComponent = [{ id: "g", list: { records: [rec(1, { agile_lane_component: "Checkout" })] } }];
    expect(buildLanes(byComponent, "component", "No component").map((lane) => lane.label)).toEqual(["Checkout"]);
    const byLabel = [{ id: "g", list: { records: [rec(1, { agile_lane_label: "alpha" }), rec(2, {})] } }];
    expect(buildLanes(byLabel, "label", "No label").map((lane) => lane.label)).toEqual(["alpha", "No label"]);
    const lanes = buildLanes(groups, "filter:5", "Everything else", { name: "Urgent work", ids: new Set([2]) });
    expect(lanes.map((lane) => lane.label)).toEqual(["Urgent work", "Everything else"]);
    expect(lanes[0].cells[0].records.map((record) => record.id)).toEqual([2]);
    expect(laneFilterId("filter:5")).toBe(5);
    expect(laneFilterId("epic")).toBe(null);
});

const QUERY = { id: 5, name: "In flight", domain: [["project_id", "=", 7], ["stage_id", "=", 3]] };

test("a board query shows as a chip, starts on and can be switched off by anyone", async () => {
    const { searchModel } = await mountBar({ options: { ...OPTIONS, query: QUERY } });
    expect(queryAllTexts("[data-chip]")).toEqual(["Query: In flight", "Mine", "Blocked", "Flagged"]);
    expect("[data-chip=query]").toHaveAttribute("aria-pressed", "true");
    const item = searchModel.items.find((entry) => entry.agileBoardQuery);
    expect(item.domain).toBe(JSON.stringify(QUERY.domain));
    expect(item.isActive).toBe(true);
    expect("[data-pick=query]").toHaveCount(0);
    await click("[data-chip=query]");
    await animationFrame();
    expect(item.isActive).toBe(false);
    expect("[data-chip=query]").toHaveAttribute("aria-pressed", "false");
});

test("the board query does not count as a filter the person saved", async () => {
    const { saves } = await mountBar({ options: { ...OPTIONS, query: QUERY } });
    await click("[data-chip=mine]");
    await animationFrame();
    expect(saves.at(-1).filters).toEqual(["mine"]);
});

test("a manager picks the board query and the board follows", async () => {
    const calls = [];
    onRpc("project.project", "agile_set_board_query", ({ kwargs }) => {
        calls.push(kwargs.filter_id);
        return kwargs.filter_id ? { id: 6, name: "Late", domain: [["project_id", "=", 7]] } : false;
    });
    const { searchModel } = await mountBar({
        options: { ...OPTIONS, query: QUERY, can_edit_query: true, query_choices: [{ id: 5, name: "In flight" }, { id: 6, name: "Late" }] },
    });
    expect(queryAllTexts("[data-pick=query] option")).toEqual(["No query", "In flight", "Late"]);
    expect(queryOne("[data-pick=query]").value).toBe("5");
    await select("6", { target: "[data-pick=query]" });
    await animationFrame();
    expect(calls).toEqual([6]);
    const queries = searchModel.items.filter((entry) => entry.agileBoardQuery);
    expect(queries.map((entry) => entry.isActive)).toEqual([false, true]);
    expect(queryAllTexts("[data-chip]")[0]).toBe("Query: Late");
    const pick = queryOne("[data-pick=query]");
    pick.value = "";
    pick.dispatchEvent(new Event("change", { bubbles: true }));
    await animationFrame();
    await animationFrame();
    expect(calls).toEqual([6, false]);
    expect(searchModel.items.filter((entry) => entry.agileBoardQuery && entry.isActive)).toHaveLength(0);
    expect(queryAllTexts("[data-chip]")).toEqual(["Mine", "Blocked", "Flagged"]);
});

test("a query that cannot run says so and does not hide issues", async () => {
    const { searchModel } = await mountBar({ options: { ...OPTIONS, query: { ...QUERY, domain: null } } });
    expect(queryAllTexts("[data-chip]")).toEqual(["Mine", "Blocked", "Flagged"]);
    expect("[data-chip-note=query]").toHaveText("The query In flight cannot run, so every issue shows.");
    expect(searchModel.items.filter((entry) => entry.agileBoardQuery)).toHaveLength(0);
});

// ---- R-1107: several boards per project ----

const BOARDS = [
    { id: 0, name: "Default board", is_default: true },
    { id: 5, name: "Payments squad", is_default: false },
];

async function mountBoards({ current = BOARDS[0], swimlane = "none" } = {}) {
    const searchModel = proxy(fakeSearchModel());
    const calls = { switched: [], columns: [], swimlanes: [], copied: [] };
    let board = current;
    class BoardsHost extends Component {
        static components = { AgileBoardBar };
        props = useProps({ calls: t.any() });
        static template = xml`<AgileBoardBar projectId="7" filterKey="this.key" swimlane="this.state.swimlane"
            onSwimlane="(value) => this.onLane(value)" onColumns="(ids) => this.props.calls.columns.push(ids)"/>`;
        setup() {
            this.state = proxy({ swimlane });
        }
        get key() {
            return "boards";
        }
        onLane(value) {
            this.props.calls.swimlanes.push(value);
            this.state.swimlane = value;
        }
    }
    onRpc("project.project", "agile_board_options", () => ({
        ...OPTIONS,
        can_edit_query: true,
        swimlane: board.is_default ? "none" : "assignee",
        boards: BOARDS,
        board: { ...board, column_ids: board.is_default ? [] : [11, 12] },
    }));
    onRpc("project.project", "agile_board_switch", ({ kwargs }) => {
        calls.switched.push(kwargs.board_id);
        board = BOARDS.find((entry) => entry.id === (kwargs.board_id || 0));
        return true;
    });
    onRpc("project.project", "agile_board_copy", ({ kwargs }) => {
        calls.copied.push(kwargs.board_id);
        board = BOARDS[1];
        return { id: 5, name: "Payments squad copy" };
    });
    await makeTestApp();
    await mountWithCleanup(BoardsHost, { props: { calls }, componentEnv: { searchModel } });
    await animationFrame();
    return calls;
}

test("the board picker shows only when the project has more than one board", async () => {
    await mountBoards();
    expect(queryAllTexts("[data-pick=board] option")).toEqual(["Default board", "Payments squad"]);
    expect(queryOne("[data-pick=board]").value).toBe("0");
});

test("choosing a board saves it, then tells the board its columns and swimlane", async () => {
    const calls = await mountBoards();
    await select("5", { target: "[data-pick=board]" });
    await animationFrame();
    expect(calls.switched).toEqual([5]);
    expect(calls.columns.at(-1)).toEqual([11, 12]);
    expect(calls.swimlanes).toEqual(["assignee"]);
    expect(queryOne("[data-pick=board]").value).toBe("5");
    await select("0", { target: "[data-pick=board]" });
    await animationFrame();
    expect(calls.switched).toEqual([5, false]);
    expect(calls.columns.at(-1)).toEqual([]);
});

test("copying a board switches to the copy", async () => {
    const calls = await mountBoards();
    await click("[data-chip-action=copy-board]");
    await animationFrame();
    expect(calls.copied).toEqual([false]);
    expect(calls.switched).toEqual([5]);
    expect(queryOne("[data-pick=board]").value).toBe("5");
});

// ---- R-1109: board insights ----

const INSIGHTS = {
    in_progress: { count: 2, average_days: 4.5, oldest: [{ id: 1, key: "WALK-1", name: "Old one", days: 8 }] },
    cycle_time: {
        series: [
            { week: "2026-10-12", average: null, count: 0 },
            { week: "2026-10-19", average: 4, count: 2 },
            { week: "2026-10-26", average: 2, count: 1 },
        ],
        recent_average: 3,
        trend: "faster",
        finished: 3,
    },
    blocked: { count: 1 },
};

test("the Insights chip opens a panel with age, cycle time and blocked", async () => {
    onRpc("project.project", "agile_board_insights", () => INSIGHTS);
    const { searchModel } = await mountBar();
    expect(".o_ag_insights").toHaveCount(0);
    await click("[data-chip-action=insights]");
    await animationFrame();
    expect(queryOne("[data-chip-action=insights]").getAttribute("aria-pressed")).toBe("true");
    expect(queryAllTexts(".o_ag_insight_title")).toEqual(["Work in progress", "Cycle time, last 8 weeks", "Blocked"]);
    expect(queryOne(".o_ag_insight_age").textContent).toInclude("WALK-1");
    expect(queryOne(".o_ag_insight_cycle .o_ag_insight_value").textContent).toInclude("Getting faster");
    expect(".o_ag_insight_bar").toHaveCount(3);
    await click(".o_ag_insight_blocked .o_ag_chip");
    await animationFrame();
    expect(searchModel.items[1].isActive).toBe(true);
    await click("[data-chip-action=insights]");
    await animationFrame();
    expect(".o_ag_insights").toHaveCount(0);
});

test("when the insights cannot load the panel says so and offers a retry", async () => {
    onRpc("project.project", "agile_board_insights", () => {
        throw new Error("nope");
    });
    await mountBar();
    await click("[data-chip-action=insights]");
    await animationFrame();
    expect(queryOne(".o_ag_insights").textContent).toInclude("Insights could not load");
    expect(".o_ag_insights .btn-link").toHaveCount(1);
});

// ---- R-1111: merged columns ----

function fakeGroup(id, stageId, name, records = []) {
    return { id, value: [stageId, name], displayName: name, isFolded: false, list: { records } };
}

test("a merged column stands in for its landing status and holds the cards of all its statuses", () => {
    const todo = fakeGroup("g1", 1, "To Do", ["a"]);
    const review = fakeGroup("g3", 3, "Review", ["b"]);
    const testing = fakeGroup("g4", 4, "Testing", ["c", "d"]);
    const units = mergeColumns([todo, review, testing], [
        { name: "Start", stage_ids: [1], landing_id: 1 },
        { name: "In review", stage_ids: [3, 4], landing_id: 4 },
    ]);
    expect(units.map((unit) => unit.displayName)).toEqual(["Start", "In review"]);
    expect(units[0].merged).toBe(false);
    expect(units[1].merged).toBe(true);
    expect(units[1].id).toBe("g4"); // a drop here lands in Testing
    expect(units[1].list.records).toEqual(["b", "c", "d"]);
    expect(units[1].members.map((group) => group.displayName)).toEqual(["Review", "Testing"]);
});

test("statuses missing from the board or the list are left out, and an empty column disappears", () => {
    const review = fakeGroup("g3", 3, "Review");
    const units = mergeColumns([review], [
        { name: "Gone", stage_ids: [9], landing_id: 9 },
        { name: "In review", stage_ids: [3, 4], landing_id: 4 },
    ]);
    expect(units.map((unit) => unit.displayName)).toEqual(["In review"]);
    expect(units[0].id).toBe("g3"); // the landing status is not loaded, so the first status takes over
    expect(units[0].merged).toBe(false);
});

test("choosing a board with merged columns tells the board its columns and groups", async () => {
    const groups = [{ name: "In review", stage_ids: [3, 4], landing_id: 3 }];
    const seen = [];
    class GroupsHost extends Component {
        static components = { AgileBoardBar };
        props = useProps({ seen: t.any() });
        static template = xml`<AgileBoardBar projectId="7" filterKey="'k'" swimlane="'none'" onSwimlane="() => {}"
            onColumns="(ids, groups) => this.props.seen.push([ids, groups])"/>`;
    }
    onRpc("project.project", "agile_board_options", () => ({
        ...OPTIONS,
        boards: BOARDS,
        board: { ...BOARDS[1], column_ids: [3, 4], column_groups: groups },
    }));
    onRpc("project.project", "agile_board_switch", () => true);
    await makeTestApp();
    await mountWithCleanup(GroupsHost, { props: { seen }, componentEnv: { searchModel: proxy(fakeSearchModel()) } });
    await animationFrame();
    await select("5", { target: "[data-pick=board]" });
    await animationFrame();
    expect(seen.at(-1)).toEqual([[3, 4], groups]);
});

test("Compact cards chip toggles and is remembered", async () => {
    await mountBar();
    expect(".o_ag_compact_btn").toHaveAttribute("aria-pressed", "false");
    await click(".o_ag_compact_btn");
    await animationFrame();
    expect(".o_ag_compact_btn").toHaveAttribute("aria-pressed", "true");
    await click(".o_ag_compact_btn");
    await animationFrame();
    expect(".o_ag_compact_btn").toHaveAttribute("aria-pressed", "false");
});

test("the Filters and views button opens and folds the bar for phones (NU-38)", async () => {
    await mountBar();
    expect(".o_ag_board_bar").not.toHaveClass("o_ag_bar_open");
    expect(".o_ag_bar_toggle").toHaveAttribute("aria-expanded", "false");
    await click(".o_ag_bar_toggle");
    await animationFrame();
    expect(".o_ag_board_bar").toHaveClass("o_ag_bar_open");
    expect(".o_ag_bar_toggle").toHaveAttribute("aria-expanded", "true");
});
