import { registry } from "@web/core/registry";

// Both tours start from the Projects list and open "Tour Project", the project
// the Python test (and docs/qa) create: a Scrum project with an active sprint,
// one epic with a child and a few loose issues.
// A project card opens the Summary; the Board is its sidebar entry. The project form (with the Backlog button) opens from the list.
const OPEN_BOARD = [
    {
        content: "Open the Tour Project",
        trigger: '.o_kanban_record:contains("Tour Project")',
        run: "click",
    },
    {
        content: "Open the Board from the sidebar",
        trigger: '.o_ag_side_item:has(.o_ag_side_label:contains("Board")):not(.o_ag_side_board)',
        run: "click",
    },
];
const OPEN_FORM = [
    {
        content: "Switch the projects to the list",
        trigger: ".o_switch_view.o_list",
        run: "click",
    },
    {
        content: "Open the Tour Project form",
        trigger: '.o_data_row:contains("Tour Project") td[name="name"]',
        run: "click",
    },
];

registry.category("web_tour.tours").add("agile_backlog_tour", {
    steps: () => [
        ...OPEN_FORM,
        {
            content: "Open the backlog",
            trigger: 'button[name="action_backlog"]',
            run: "click",
        },
        {
            content: "The Backlog section starts folded; open it",
            trigger: '.o_group_header:contains("Backlog")',
            run: "click",
        },
        {
            content: "Its issues show",
            trigger: '.o_data_row:contains("Loose issue")',
        },
        {
            content: "The epic panel lists the epic with its progress",
            trigger: '.o_ag_epics .o_ag_epic:contains("Tour epic")',
            run: "click",
        },
        {
            content: "Choosing the epic adds a filter",
            trigger: '.o_searchview_facet:contains("Epic: Tour epic")',
        },
        {
            content: "Only the epic's child is left",
            trigger: '.o_data_row:contains("Epic child")',
        },
        {
            content: "Loose issues are filtered out",
            trigger: "body:not(:has(.o_data_row:contains('Loose issue')))",
        },
        {
            content: "Choosing the epic again clears the filter",
            trigger: '.o_ag_epics .o_ag_epic[aria-pressed="true"]',
            run: "click",
        },
        {
            content: "The filter is gone",
            trigger: "body:not(:has(.o_searchview_facet:contains('Epic: Tour epic')))",
        },
        {
            content: "Loose issues are back",
            trigger: '.o_data_row:contains("Loose issue")',
        },
        {
            content: "Type a new issue into a section",
            trigger: ".o_ag_quick_input",
            run: "edit Tour quick issue",
        },
        {
            content: "Enter creates it",
            trigger: ".o_ag_quick_input",
            run: "press Enter",
        },
        {
            content: "The new issue appears in the list",
            trigger: '.o_data_row:contains("Tour quick issue")',
        },
        {
            content: "Click its points to edit them",
            trigger: '.o_data_row:contains("Tour quick issue") td[name="story_points"]',
            run: "click",
        },
        {
            content: "Type an estimate",
            trigger: ".o_ag_inline input",
            run: "edit 3",
        },
        {
            content: "Enter saves it",
            trigger: ".o_ag_inline input",
            run: "press Enter",
        },
        {
            content: "The estimate shows in the row",
            trigger: '.o_data_row:contains("Tour quick issue") td[name="story_points"]:contains("3.00")',
        },
    ],
});

registry.category("web_tour.tours").add("agile_board_tour", {
    steps: () => [
        ...OPEN_BOARD,
        {
            content: "The board shows the active sprint's columns",
            trigger: ".o_kanban_group .o_kanban_record",
        },
        {
            content: "Switch the Mine chip on",
            trigger: '.o_ag_chip[data-chip="mine"]',
            run: "click",
        },
        {
            content: "It appears as a search facet",
            trigger: '.o_searchview_facet:contains("My Issues")',
        },
        {
            content: "Switch it off",
            trigger: '.o_ag_chip[data-chip="mine"][aria-pressed="true"]',
            run: "click",
        },
        {
            content: "The facet is gone",
            trigger: "body:not(:has(.o_searchview_facet:contains('My Issues')))",
        },
        {
            content: "Split the board into swimlanes by assignee",
            trigger: '.o_ag_lane_select',
            run: "select assignee",
        },
        {
            content: "Swimlane rows appear",
            trigger: ".o_ag_swimlanes .o_ag_lane",
        },
        {
            content: "Turn swimlanes off",
            trigger: '.o_ag_lane_select',
            run: "select none",
        },
        {
            content: "The normal columns are back",
            trigger: "body:not(:has(.o_ag_swimlanes))",
        },
        {
            content: "Click a card to open the drawer",
            trigger: '.o_kanban_record:contains("Tour issue A")',
            run: "click",
        },
        {
            content: "Rename the issue in the drawer",
            trigger: '.o_ag_drawer [name="name"] input',
            run: "edit Tour issue A renamed",
        },
        {
            content: "Done saves and closes",
            trigger: ".o_ag_drawer_close",
            run: "click",
        },
        {
            content: "The drawer is closed",
            trigger: "body:not(:has(.o_ag_drawer))",
        },
        {
            content: "The card shows the new title",
            trigger: '.o_kanban_record:contains("Tour issue A renamed")',
        },
        {
            content: "Add an issue from a column",
            trigger: ".o_kanban_group .o_kanban_quick_add",
            run: "click",
        },
        {
            content: "Type its title",
            trigger: '.o_kanban_quick_create [name="display_name"] input',
            run: "edit Tour board quick",
        },
        {
            content: "Add it",
            trigger: ".o_kanban_quick_create .o_kanban_add",
            run: "click",
        },
        {
            content: "The new card is on the board",
            trigger: '.o_kanban_record:contains("Tour board quick")',
        },
    ],
});
