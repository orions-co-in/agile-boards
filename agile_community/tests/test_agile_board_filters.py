import json

from unittest.mock import patch

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user
from .pro_guard import needs_pro


class FiltersCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(
            cls.env, login="agile_filters_manager", groups="project.group_project_manager"
        )
        cls.other = new_test_user(
            cls.env, login="agile_filters_other", groups="project.group_project_manager"
        )
        cls.outsider = new_test_user(
            cls.env, login="agile_filters_outsider", groups="project.group_project_user"
        )
        cls.project = cls.env["project.project"].with_user(cls.manager).create({
            "name": "Filters",
            "privacy_visibility": "employees",
            "agile_enabled": True,
            "agile_key": "FLT",
            "agile_method": "scrum",
        })
        cls.env["agile.project.member"].create({
            "project_id": cls.project.id, "user_id": cls.other.id, "role": "manager",
        })
        cls.epic_type = cls.env["agile_community.task_type"].search(
            [("is_epic", "=", True)], limit=1
        )
        cls.epic = cls.env["project.task"].with_user(cls.manager).create({
            "name": "Search",
            "project_id": cls.project.id,
            "agile_task_type_id": cls.epic_type.id,
            "description": "Epic",
        })

    def _options(self, user=None):
        return self.project.with_user(user or self.manager).agile_board_options()


class TestAgileBoardFilters(FiltersCase):

    def test_options_default_to_no_swimlane_and_no_filters(self):
        options = self._options()
        self.assertEqual(options["swimlane"], "none")
        self.assertEqual(options["filters"], [])
        self.assertTrue(options["task_types"])
        self.assertNotIn(self.epic_type.id, [t["id"] for t in options["task_types"]])
        self.assertEqual([e["id"] for e in options["epics"]], [self.epic.id])

    def test_choices_are_saved_per_person_and_project(self):
        self.project.with_user(self.manager).agile_save_board_options(
            swimlane="assignee", filters=["mine", f"epic:{self.epic.id}"]
        )
        options = self._options()
        self.assertEqual(options["swimlane"], "assignee")
        self.assertEqual(options["filters"], ["mine", f"epic:{self.epic.id}"])
        self.assertEqual(self._options(self.other)["swimlane"], "none")
        self.assertEqual(self._options(self.other)["filters"], [])

    def test_saving_one_part_keeps_the_other(self):
        project = self.project.with_user(self.manager)
        project.agile_save_board_options(swimlane="epic", filters=["blocked"])
        project.agile_save_board_options(filters=["mine"])
        self.assertEqual(self._options()["swimlane"], "epic")
        project.agile_save_board_options(swimlane="none")
        self.assertEqual(self._options()["filters"], ["mine"])

    def test_clearing_filters_is_saved(self):
        project = self.project.with_user(self.manager)
        project.agile_save_board_options(filters=["mine"])
        project.agile_save_board_options(filters=[])
        self.assertEqual(self._options()["filters"], [])

    def test_unknown_swimlane_and_filters_are_refused(self):
        project = self.project.with_user(self.manager)
        with self.assertRaises(ValidationError):
            project.agile_save_board_options(swimlane="sprint")
        for bad in (["everything"], ["epic:abc"], ["type:1;drop"], ["mine"] * 9):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                project.agile_save_board_options(filters=bad)

    def test_new_swimlane_kinds_are_saved_and_lane_labels_are_computed(self):
        project = self.project.with_user(self.manager)
        for kind in ("priority", "component", "label"):
            project.agile_save_board_options(swimlane=kind)
            self.assertEqual(self._options()["swimlane"], kind)
        tag_b, tag_a = self.env["project.tags"].create([{"name": "bravo"}, {"name": "alpha"}])
        issue = self.env["project.task"].with_user(self.manager).create({
            "name": "Laned", "project_id": self.project.id, "description": "x", "priority": "1",
            "tag_ids": [(6, 0, (tag_b | tag_a).ids)],
        })
        self.assertEqual(issue.agile_lane_priority, dict(issue._fields["priority"].selection)["1"])
        self.assertEqual(issue.agile_lane_label, "alpha", "the first label by name")
        self.assertEqual(issue.agile_lane_component, issue.agile_component_id.name or "")
        bare = self.env["project.task"].with_user(self.manager).create({
            "name": "Bare", "project_id": self.project.id, "description": "x",
        })
        self.assertEqual(bare.agile_lane_label, "")

    def test_a_saved_filter_swimlane_lists_its_issues_and_is_checked(self):
        project = self.project.with_user(self.manager)
        saved = self.env["agile.filter"].with_user(self.manager).create({
            "name": "Mine to review", "project_id": self.project.id, "query": 'status = "Backlog"',
            "visibility": "shared",
        })
        issue = self.env["project.task"].with_user(self.manager).create({
            "name": "In filter", "project_id": self.project.id, "description": "x",
        })
        self.assertEqual([f["name"] for f in self._options()["lane_filters"]], ["Mine to review"])
        project.agile_save_board_options(swimlane=f"filter:{saved.id}")
        self.assertEqual(self._options()["swimlane"], f"filter:{saved.id}")
        result = project.agile_board_filter_ids(saved.id)
        self.assertEqual(result["name"], "Mine to review")
        self.assertIn(issue.id, result["ids"])
        with self.assertRaises(ValidationError):
            project.agile_save_board_options(swimlane="filter:999999")
        with self.assertRaises(ValidationError):
            project.agile_save_board_options(swimlane="filter:abc")
        with self.assertRaises(ValidationError):
            project.agile_board_filter_ids(999999)
        project.agile_save_board_view("By filter", [], f"filter:{saved.id}")
        self.assertEqual(self._options()["views"][-1]["swimlane"], f"filter:{saved.id}")

    def test_private_filters_of_others_are_not_offered_as_swimlanes(self):
        self.env["agile.filter"].with_user(self.other).create({
            "name": "Hidden plan", "project_id": self.project.id, "query": 'status = "To Do"', "visibility": "private",
        })
        names = [f["name"] for f in self._options()["lane_filters"]]
        self.assertNotIn("Hidden plan", names)

    def test_people_outside_the_project_cannot_read_or_save(self):
        self.project.write({"privacy_visibility": "followers"})
        project = self.project.with_user(self.outsider)
        with self.assertRaises(AccessError):
            project.agile_board_options()
        with self.assertRaises(AccessError):
            project.agile_save_board_options(swimlane="epic")

    def test_board_action_carries_the_swimlane_not_a_group_by(self):
        self.project.with_user(self.manager).agile_save_board_options(swimlane="epic")
        action = self.project.with_user(self.manager).action_view_tasks()
        self.assertEqual(action["context"]["agile_swimlane"], "epic")
        self.assertFalse(
            [key for key in action["context"] if key.startswith("search_default_agile_group_by")]
        )
        other = self.project.with_user(self.other).action_view_tasks()
        self.assertEqual(other["context"]["agile_swimlane"], "none")

    def test_lane_labels_name_the_assignee_and_the_epic(self):
        issue = self.env["project.task"].with_user(self.manager).create({
            "name": "Child",
            "project_id": self.project.id,
            "parent_id": self.epic.id,
            "user_ids": [(6, 0, [self.other.id])],
        })
        self.assertEqual(issue.agile_lane_assignee, self.other.name)
        self.assertEqual(issue.agile_lane_epic, f"{self.epic.issue_key} Search")
        lonely = self.env["project.task"].with_user(self.manager).create({
            "name": "Alone", "project_id": self.project.id, "user_ids": [(5, 0, 0)],
        })
        self.assertEqual(lonely.agile_lane_assignee, "")
        self.assertEqual(lonely.agile_lane_epic, "")


class TestAgileSummaryLayout(FiltersCase):
    """S-934: each person arranges their own Summary tiles for each project."""

    def _layout(self, user=None):
        return self.project.with_user(user or self.manager).agile_summary_layout()

    def _ids(self, layout):
        return [entry["id"] for entry in layout]

    def test_default_layout_shows_every_tile_in_order(self):
        layout = self._layout()
        self.assertEqual(
            self._ids(layout),
            ["pulse", "counts", "status", "flow", "load", "types", "epics", "release", "activity"],
        )
        self.assertFalse(any(entry["hidden"] for entry in layout))
        self.assertEqual(self.project.with_user(self.manager).agile_summary_data()["layout"], layout)

    def test_saved_order_and_hidden_tiles_come_back(self):
        order = ["status", "pulse", "counts", "flow", "load", "types", "epics", "release", "activity"]
        self.project.with_user(self.manager).agile_save_summary_layout(
            [{"id": tile, "hidden": tile == "types"} for tile in order]
        )
        layout = self._layout()
        self.assertEqual(self._ids(layout), order)
        self.assertEqual([e["id"] for e in layout if e["hidden"]], ["types"])

    def test_layout_is_private_to_the_person(self):
        self.project.with_user(self.manager).agile_save_summary_layout(
            [{"id": "flow", "hidden": True}]
        )
        self.assertTrue(next(e for e in self._layout() if e["id"] == "flow")["hidden"])
        self.assertFalse(next(e for e in self._layout(self.other) if e["id"] == "flow")["hidden"])

    def test_missing_tiles_are_appended_and_unknown_ones_are_refused(self):
        self.project.with_user(self.manager).agile_save_summary_layout([{"id": "activity", "hidden": False}])
        layout = self._layout()
        self.assertEqual(layout[0]["id"], "activity")
        self.assertEqual(len(layout), 9)
        with self.assertRaises(ValidationError):
            self.project.with_user(self.manager).agile_save_summary_layout([{"id": "nope"}])
        with self.assertRaises(ValidationError):
            self.project.with_user(self.manager).agile_save_summary_layout(
                [{"id": "pulse"}, {"id": "pulse"}]
            )

    def test_at_least_one_tile_stays_shown(self):
        every_tile = ["pulse", "counts", "status", "flow", "load", "types", "epics", "release", "activity"]
        with self.assertRaises(ValidationError):
            self.project.with_user(self.manager).agile_save_summary_layout(
                [{"id": tile, "hidden": True} for tile in every_tile]
            )

    def test_reset_restores_the_default(self):
        self.project.with_user(self.manager).agile_save_summary_layout([{"id": "activity", "hidden": True}])
        layout = self.project.with_user(self.manager).agile_save_summary_layout(None)
        self.assertEqual(self._ids(layout)[0], "pulse")
        self.assertFalse(any(entry["hidden"] for entry in layout))

    def test_non_members_cannot_read_or_save(self):
        self.project.write({"privacy_visibility": "followers"})
        with self.assertRaises(AccessError):
            self._layout(self.outsider)
        with self.assertRaises(AccessError):
            self.project.with_user(self.outsider).agile_save_summary_layout(None)


class TestAgileBoardViews(FiltersCase):
    """S-933: a person keeps named combinations of board filters and swimlane."""

    def _views(self, user=None):
        return self._options(user)["views"]

    def test_save_switch_replace_and_delete_a_view(self):
        project = self.project.with_user(self.manager)
        self.assertEqual(self._views(), [])
        project.agile_save_board_view("My work", ["mine", "blocked"], "epic")
        self.assertEqual(self._views(), [{"name": "My work", "filters": ["mine", "blocked"], "swimlane": "epic"}])
        project.agile_save_board_view("my WORK", ["review"], "none")
        self.assertEqual(self._views(), [{"name": "my WORK", "filters": ["review"], "swimlane": "none"}])
        project.agile_save_board_view("Search epic", [f"epic:{self.epic.id}"], "assignee")
        self.assertEqual([v["name"] for v in self._views()], ["my WORK", "Search epic"])
        project.agile_delete_board_view("MY work")
        self.assertEqual([v["name"] for v in self._views()], ["Search epic"])

    def test_views_are_private_to_the_person(self):
        self.project.with_user(self.manager).agile_save_board_view("Mine", ["mine"], "none")
        self.assertEqual(self._views(self.other), [])

    def test_bad_input_is_refused(self):
        project = self.project.with_user(self.manager)
        with self.assertRaises(ValidationError):
            project.agile_save_board_view("  ", ["mine"], "none")
        with self.assertRaises(ValidationError):
            project.agile_save_board_view("x" * 41, ["mine"], "none")
        with self.assertRaises(ValidationError):
            project.agile_save_board_view("Bad", ["nope"], "none")
        with self.assertRaises(ValidationError):
            project.agile_save_board_view("Bad", ["mine"], "diagonal")

    def test_at_most_ten_views(self):
        project = self.project.with_user(self.manager)
        for index in range(10):
            project.agile_save_board_view(f"View {index}", ["mine"], "none")
        with self.assertRaises(ValidationError):
            project.agile_save_board_view("One too many", ["mine"], "none")
        project.agile_save_board_view("View 3", ["blocked"], "none")  # replacing is still fine
        self.assertEqual(len(self._views()), 10)

    def test_people_outside_the_project_cannot_save_or_delete(self):
        self.project.write({"privacy_visibility": "followers"})
        project = self.project.with_user(self.outsider)
        with self.assertRaises(AccessError):
            project.agile_save_board_view("Mine", ["mine"], "none")
        with self.assertRaises(AccessError):
            project.agile_delete_board_view("Mine")


class TestAgileBoardQuery(FiltersCase):
    """R-1101: the board starts limited to one shared saved filter."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Filter = cls.env["agile.filter"]
        cls.shared = Filter.with_user(cls.manager).create({
            "name": "In flight", "project_id": cls.project.id, "visibility": "shared",
            "query": 'status = "In Progress"',
        })
        cls.private = Filter.with_user(cls.manager).create({
            "name": "Mine only", "project_id": cls.project.id, "visibility": "private",
            "query": 'status = "In Progress"',
        })

    def test_no_query_by_default(self):
        options = self._options()
        self.assertIsNone(options["query"])
        self.assertTrue(options["can_edit_query"])
        self.assertEqual([c["id"] for c in options["query_choices"]], [self.shared.id])

    def test_manager_sets_the_query_and_everyone_gets_its_domain(self):
        result = self.project.with_user(self.manager).agile_set_board_query(self.shared.id)
        self.assertEqual(result["id"], self.shared.id)
        for user in (self.manager, self.other):
            query = self._options(user)["query"]
            self.assertEqual(query["name"], "In flight")
            self.assertTrue(query["domain"])
            json.dumps(query["domain"])  # it travels to the browser as JSON

    def test_clearing_the_query(self):
        self.project.with_user(self.manager).agile_set_board_query(self.shared.id)
        self.assertIsNone(self.project.with_user(self.manager).agile_set_board_query(False))
        self.assertIsNone(self._options()["query"])

    def test_only_a_shared_filter_of_this_project_counts(self):
        with self.assertRaises(ValidationError):
            self.project.with_user(self.manager).agile_set_board_query(self.private.id)
        with self.assertRaises(ValidationError):
            self.project.with_user(self.manager).agile_set_board_query(999999)

    def test_only_a_manager_changes_it(self):
        member = new_test_user(self.env, login="agile_filters_member", groups="project.group_project_user")
        self.env["agile.project.member"].create({"project_id": self.project.id, "user_id": member.id, "role": "contributor"})
        options = self._options(member)
        self.assertFalse(options["can_edit_query"])
        self.assertEqual(options["query_choices"], [])
        with self.assertRaises(AccessError):
            self.project.with_user(member).agile_set_board_query(self.shared.id)
        with self.assertRaises(AccessError):
            self.project.with_user(self.outsider).agile_set_board_query(self.shared.id)

    def test_deleting_the_saved_filter_clears_the_query(self):
        self.project.with_user(self.manager).agile_set_board_query(self.shared.id)
        self.shared.unlink()
        self.assertIsNone(self._options()["query"])

    def test_a_query_that_no_longer_runs_has_no_domain(self):
        self.project.with_user(self.manager).agile_set_board_query(self.shared.id)
        with patch.object(type(self.shared), "_issue_domain", side_effect=UserError("Unknown field 'gone'.")):
            query = self._options()["query"]
        self.assertEqual(query["name"], "In flight")
        self.assertIsNone(query["domain"])

    @needs_pro("agile.audit")
    def test_changes_are_audited(self):
        Audit = self.env["agile.audit"].sudo()
        before = Audit.search_count([("project_id", "=", self.project.id), ("area", "=", "boards")])
        self.project.with_user(self.manager).agile_set_board_query(self.shared.id)
        self.project.with_user(self.manager).agile_set_board_query(self.shared.id)  # no change, no entry
        self.project.with_user(self.manager).agile_set_board_query(False)
        rows = Audit.search([("project_id", "=", self.project.id), ("area", "=", "boards")], order="id")
        self.assertEqual(len(rows) - before, 2)
        self.assertEqual(rows[-2:].mapped("text"), ["Board query set to In flight.", "Board query removed."])
