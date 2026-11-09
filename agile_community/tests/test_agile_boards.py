from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user
from .pro_guard import needs_pro


class TestAgileBoards(TransactionCase):
    """R-1107: several shared boards per project; the Default board stays as it was."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, login="boards_manager", groups="project.group_project_manager")
        cls.contributor = new_test_user(cls.env, login="boards_contributor", groups="project.group_project_user")
        cls.outsider = new_test_user(cls.env, login="boards_outsider", groups="project.group_project_user")
        cls.project = cls.env["project.project"].with_user(cls.manager).create({
            "name": "Boards", "agile_enabled": True, "agile_key": "BRD", "agile_method": "kanban",
            "privacy_visibility": "employees",
        })
        cls.project.agile_member_ids.filtered(lambda m: m.user_id == cls.contributor).role = "contributor"
        cls.Board = cls.env["agile.board"]
        cls.shared = cls.env["agile.filter"].with_user(cls.manager).create({
            "name": "Payments", "project_id": cls.project.id, "visibility": "shared", "query": 'status = "In Progress"',
        })
        cls.stages = cls.env["project.task.type"].with_context(active_test=False).search(
            [("project_ids", "=", cls.project.id), ("agile_status", "in", ["ready", "progress"])]
        )

    def _board(self, name="Payments squad", **extra):
        return self.Board.with_user(self.manager).create({"project_id": self.project.id, "name": name, **extra})

    def _options(self, user=None):
        return self.project.with_user(user or self.manager).agile_board_options()

    def test_a_project_starts_with_only_the_default_board(self):
        options = self._options()
        self.assertEqual([b["name"] for b in options["boards"]], ["Default board"])
        self.assertTrue(options["board"]["is_default"])
        self.assertEqual(options["board"]["column_ids"], [])

    def test_a_manager_adds_a_board_with_its_own_query_columns_and_swimlane(self):
        board = self._board(query_id=self.shared.id, column_ids=[(6, 0, self.stages.ids)], swimlane="assignee")
        self.project.with_user(self.manager).agile_board_switch(board.id)
        options = self._options()
        self.assertEqual([b["name"] for b in options["boards"]], ["Default board", "Payments squad"])
        self.assertEqual(options["board"]["name"], "Payments squad")
        self.assertEqual(sorted(options["board"]["column_ids"]), sorted(self.stages.ids))
        self.assertEqual(options["swimlane"], "assignee")
        self.assertEqual(options["query"]["id"], self.shared.id)

    def test_each_person_has_their_own_current_board(self):
        board = self._board()
        self.project.with_user(self.manager).agile_board_switch(board.id)
        self.assertEqual(self._options()["board"]["id"], board.id)
        self.assertTrue(self._options(self.contributor)["board"]["is_default"])
        self.project.with_user(self.manager).agile_board_switch(False)
        self.assertTrue(self._options()["board"]["is_default"])

    def test_the_default_board_keeps_the_project_query_and_boards_have_their_own(self):
        self.project.with_user(self.manager).agile_set_board_query(self.shared.id)
        board = self._board()
        self.assertEqual(self._options()["query"]["id"], self.shared.id)  # Default board
        self.project.with_user(self.manager).agile_board_switch(board.id)
        self.assertIsNone(self._options()["query"])
        other = self.env["agile.filter"].with_user(self.manager).create({
            "name": "Late", "project_id": self.project.id, "visibility": "shared", "query": 'status = "Done"',
        })
        self.project.with_user(self.manager).agile_set_board_query(other.id)
        self.assertEqual(board.query_id, other)
        self.assertEqual(self.project.agile_board_query_id, self.shared)

    def test_copy_takes_the_settings_not_the_issues_and_names_the_copy(self):
        board = self._board(query_id=self.shared.id, swimlane="epic", column_ids=[(6, 0, self.stages.ids)])
        copy = self.project.with_user(self.manager).agile_board_copy(board.id)
        self.assertEqual(copy["name"], "Payments squad copy")
        record = self.Board.browse(copy["id"])
        self.assertEqual((record.query_id, record.swimlane, record.column_ids), (self.shared, "epic", self.stages))
        again = self.project.with_user(self.manager).agile_board_copy(board.id)
        self.assertEqual(again["name"], "Payments squad copy 2")
        from_default = self.project.with_user(self.manager).agile_board_copy(False)
        self.assertEqual(from_default["name"], "Default board copy")

    def test_names_are_unique_and_the_default_name_is_reserved(self):
        self._board("Payments squad")
        with self.assertRaises(ValidationError):
            self._board("payments SQUAD")
        with self.assertRaises(ValidationError):
            self._board("Default board")
        with self.assertRaises(ValidationError):
            self._board("   ")

    def test_a_project_keeps_up_to_ten_boards_with_the_default_one(self):
        for index in range(9):
            self._board(f"Board {index}")
        with self.assertRaises(ValidationError):
            self._board("One too many")

    def test_a_board_takes_only_shared_filters_and_columns_of_its_project(self):
        private = self.env["agile.filter"].with_user(self.manager).create({
            "name": "Mine", "project_id": self.project.id, "visibility": "private", "query": 'status = "Done"',
        })
        with self.assertRaises(ValidationError):
            self._board("Private query", query_id=private.id)
        with self.assertRaises(ValidationError):
            self._board("Bad lane", swimlane="diagonal")
        other_project = self.env["project.project"].with_user(self.manager).create({
            "name": "Other", "agile_enabled": True, "agile_key": "OTH",
        })
        foreign = self.env["project.task.type"].with_context(active_test=False).search(
            [("project_ids", "=", other_project.id), ("agile_status", "=", "ready")], limit=1
        )
        with self.assertRaises(ValidationError):
            self._board("Foreign column", column_ids=[(6, 0, foreign.ids)])

    def test_only_a_manager_changes_boards_but_everyone_on_the_team_opens_them(self):
        board = self._board()
        with self.assertRaises(AccessError):
            self.Board.with_user(self.contributor).create({"project_id": self.project.id, "name": "Mine"})
        with self.assertRaises(AccessError):
            board.with_user(self.contributor).write({"name": "Renamed"})
        with self.assertRaises(AccessError):
            board.with_user(self.contributor).unlink()
        with self.assertRaises(UserError):  # AccessError is a UserError
            self.project.with_user(self.contributor).action_agile_manage_boards()
        self.assertEqual(len(self._options(self.contributor)["boards"]), 2)
        self.project.with_user(self.contributor).agile_board_switch(board.id)
        self.assertEqual(self._options(self.contributor)["board"]["id"], board.id)

    def test_people_outside_the_team_cannot_see_or_open_boards(self):
        board = self._board()
        # Enabling the team seeds every project user; the outsider is taken off it.
        self.project.agile_member_ids.sudo().filtered(lambda m: m.user_id == self.outsider).with_context(
            agile_role_seed=True
        ).unlink()
        self.assertFalse(self.Board.with_user(self.outsider).search([("id", "=", board.id)]))
        with self.assertRaises(AccessError):
            self.project.with_user(self.outsider).agile_board_switch(board.id)

    def test_deleting_a_board_sends_people_back_to_the_default_board_and_keeps_views(self):
        board = self._board()
        project = self.project.with_user(self.manager)
        project.agile_save_board_view("Mine", ["mine"], "none")
        project.agile_board_switch(board.id)
        board.with_user(self.manager).unlink()
        options = self._options()
        self.assertTrue(options["board"]["is_default"])
        self.assertEqual([v["name"] for v in options["views"]], ["Mine"])

    def test_a_switch_to_a_missing_board_is_refused(self):
        with self.assertRaises(ValidationError):
            self.project.with_user(self.manager).agile_board_switch(999999)

    @needs_pro("agile.audit")
    def test_changes_are_audited(self):
        board = self._board("Audited")
        board.with_user(self.manager).write({"name": "Audited again"})
        board.with_user(self.manager).unlink()
        texts = self.env["agile.audit"].sudo().search(
            [("project_id", "=", self.project.id), ("area", "=", "boards")], order="id"
        ).mapped("text")
        self.assertEqual(texts, ["Board Audited added.", "Board Audited changed.", "Board Audited again deleted."])

    def test_the_sidebar_lists_boards_only_when_there_are_several(self):
        self.assertEqual(self.project.with_user(self.manager).agile_sidebar_data()["boards"], [])
        board = self._board()
        data = self.project.with_user(self.manager).agile_sidebar_data()
        self.assertEqual([b["name"] for b in data["boards"]], ["Default board", "Payments squad"])
        self.assertEqual(data["board_id"], 0)
        self.project.with_user(self.manager).agile_board_switch(board.id)
        self.assertEqual(self.project.with_user(self.manager).agile_sidebar_data()["board_id"], board.id)


class TestAgileCalendarSpans(TransactionCase):
    """R-1108: the Calendar adds sprint and release spans beside the due dates."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, login="cal_manager", groups="project.group_project_manager")
        cls.outsider = new_test_user(cls.env, login="cal_outsider", groups="project.group_project_user")
        cls.project = cls.env["project.project"].with_user(cls.manager).create({
            "name": "Calendar", "agile_enabled": True, "agile_key": "CAL", "agile_method": "scrum",
            "privacy_visibility": "employees",
        })
        cls.sprint = cls.env["project.sprint"].with_user(cls.manager).create({
            "name": "S1", "project_id": cls.project.id, "date_option": "custom",
            "date_start": "2026-11-02", "date_end": "2026-11-15",
        })
        cls.release = cls.env["project.version"].with_user(cls.manager).create({
            "name": "1.0", "project_id": cls.project.id, "release_date": "2026-11-20",
        })

    def _spans(self, start, end, user=None):
        return self.project.with_user(user or self.manager).agile_calendar_spans(start, end)

    def test_sprints_and_releases_inside_the_range_are_listed_with_their_dates(self):
        spans = {span["id"]: span for span in self._spans("2026-11-01", "2026-11-30")}
        sprint = spans[f"sprint-{self.sprint.id}"]
        self.assertEqual((sprint["start"], sprint["end"], sprint["title"]), ("2026-11-02", "2026-11-15", "Sprint: S1"))
        release = spans[f"release-{self.release.id}"]
        self.assertEqual((release["start"], release["end"], release["title"]), ("2026-11-20", "2026-11-20", "Release: 1.0"))

    def test_a_span_that_only_touches_the_range_shows_and_one_outside_does_not(self):
        self.assertEqual([s["kind"] for s in self._spans("2026-11-15", "2026-11-16")], ["sprint"])
        self.assertEqual(self._spans("2026-12-01", "2026-12-31"), [])

    def test_a_kanban_project_has_releases_but_no_sprints(self):
        self.project.agile_method = "kanban"
        self.assertEqual([s["kind"] for s in self._spans("2026-11-01", "2026-11-30")], ["release"])

    def test_other_projects_are_not_mixed_in(self):
        other = self.env["project.project"].with_user(self.manager).create({
            "name": "Other", "agile_enabled": True, "agile_key": "OTX", "agile_method": "scrum",
        })
        self.assertEqual(other.with_user(self.manager).agile_calendar_spans("2026-11-01", "2026-11-30"), [])

    def test_people_outside_the_team_get_no_spans(self):
        self.project.agile_member_ids.sudo().filtered(lambda m: m.user_id == self.outsider).with_context(
            agile_role_seed=True
        ).unlink()
        with self.assertRaises(AccessError):
            self._spans("2026-11-01", "2026-11-30", self.outsider)


class TestAgileBoardInsights(TransactionCase):
    """R-1109: age of work in progress, cycle time trend and blocked count."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, login="ins_manager", groups="project.group_project_manager")
        cls.project = cls.env["project.project"].with_user(cls.manager).create({
            "name": "Insights", "agile_enabled": True, "agile_key": "INS", "agile_method": "kanban",
        })
        cls.Task = cls.env["project.task"].with_user(cls.manager)

    def _stage(self, status):
        return self.env["project.task.type"].with_context(active_test=False).search(
            [("project_ids", "=", self.project.id), ("agile_status", "=", status)], limit=1
        )

    def _task(self, name, status):
        task = self.Task.create({"name": name, "project_id": self.project.id})
        task.sudo().write({"stage_id": self._stage(status).id})
        return task

    def _insights(self):
        return self.project.with_user(self.manager).agile_board_insights()

    def test_an_empty_board_gives_zeros_not_errors(self):
        data = self._insights()
        self.assertEqual(data["in_progress"], {"count": 0, "average_days": 0, "oldest": []})
        self.assertEqual(data["blocked"]["count"], 0)
        self.assertEqual(data["cycle_time"]["trend"], "unknown")
        self.assertEqual(len(data["cycle_time"]["series"]), 8)

    def test_only_work_in_progress_or_review_is_aged_oldest_first(self):
        old = self._task("Old", "progress")
        self._task("New", "review")
        self._task("Waiting", "ready")
        old.sudo().date_last_stage_update = fields.Datetime.now() - timedelta(days=10)
        data = self._insights()["in_progress"]
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["oldest"][0]["name"], "Old")
        self.assertGreaterEqual(data["oldest"][0]["days"], 5)

    def test_cycle_time_is_averaged_per_week_and_compared_with_the_earlier_weeks(self):
        Event = self.env["agile.issue.metric.event"].sudo().with_context(allow_agile_metric_event_write=True)
        now = fields.Datetime.now()
        for index, (days_ago, cycle) in enumerate([(2, 2.0), (3, 4.0), (40, 10.0)]):
            task = self._task(f"Done {index}", "progress")
            Event.create({
                "project_id": self.project.id, "task_id": task.id, "issue_key": f"INS-{index}",
                "issue_name": task.name, "event_type": "completed",
                "event_at": now - timedelta(days=days_ago), "cycle_time_days": cycle,
            })
        data = self._insights()["cycle_time"]
        self.assertEqual(data["finished"], 3)
        self.assertEqual(data["recent_average"], 3.0)
        self.assertEqual(data["trend"], "faster")

    def test_blocked_counts_open_blocked_issues_only(self):
        blocked = self._task("Stuck", "progress")
        blocked.sudo().write({"agile_blocked": True, "agile_block_reason": "Waiting on legal"})
        self.assertEqual(self._insights()["blocked"]["count"], 1)

    def test_people_outside_the_team_are_refused(self):
        outsider = new_test_user(self.env, login="ins_outsider", groups="project.group_project_user")
        self.project.agile_member_ids.sudo().filtered(lambda m: m.user_id == outsider).with_context(
            agile_role_seed=True
        ).unlink()
        with self.assertRaises(AccessError):
            self.project.with_user(outsider).agile_board_insights()


class TestAgileMergedColumns(TransactionCase):
    """R-1111: a board column can hold more than one workflow status."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, login="mc_manager", groups="project.group_project_manager")
        cls.contributor = new_test_user(cls.env, login="mc_contributor", groups="project.group_project_user")
        cls.project = cls.env["project.project"].with_user(cls.manager).create({
            "name": "Merged", "agile_enabled": True, "agile_key": "MRG", "agile_method": "kanban",
            "privacy_visibility": "employees",
        })
        cls.stages = cls.env["project.task.type"].with_context(active_test=False).search(
            [("project_ids", "=", cls.project.id)], order="sequence, id"
        )
        cls.Board = cls.env["agile.board"].with_user(cls.manager)

    def _board(self, groups, name="Merged board"):
        return self.Board.create({
            "project_id": self.project.id, "name": name,
            "column_group_ids": [(0, 0, group) for group in groups],
        })

    def _group(self, name, stages, landing=None, sequence=10):
        values = {"name": name, "sequence": sequence, "stage_ids": [(6, 0, stages.ids)]}
        if landing:
            values["landing_stage_id"] = landing.id
        return values

    def _options(self, board, user=None):
        project = self.project.with_user(user or self.manager)
        project.agile_board_switch(board.id)
        return project.agile_board_options()["board"]

    def test_the_board_reads_its_columns_with_statuses_in_workflow_order(self):
        first, second, third = self.stages[0], self.stages[1], self.stages[2]
        board = self._board([
            self._group("Start", first, sequence=1),
            self._group("Work", third | second, landing=third, sequence=2),
        ])
        data = self._options(board)
        self.assertEqual([g["name"] for g in data["column_groups"]], ["Start", "Work"])
        self.assertEqual(data["column_groups"][1]["stage_ids"], [second.id, third.id])
        self.assertEqual(data["column_groups"][1]["landing_id"], third.id)
        self.assertEqual(sorted(data["column_ids"]), sorted((first | second | third).ids))

    def test_the_landing_status_defaults_to_the_first_status(self):
        board = self._board([self._group("Work", self.stages[2] | self.stages[1])])
        self.assertEqual(self._options(board)["column_groups"][0]["landing_id"], self.stages[1].id)

    def test_a_status_fits_in_one_column_only(self):
        with self.assertRaises(ValidationError):
            self._board([self._group("A", self.stages[0] | self.stages[1]), self._group("B", self.stages[1])])

    def test_the_landing_status_must_be_in_the_column(self):
        with self.assertRaises(ValidationError):
            self._board([self._group("A", self.stages[0], landing=self.stages[1])])

    def test_statuses_of_another_project_are_refused(self):
        other = self.env["project.project"].with_user(self.manager).create({
            "name": "Other", "agile_enabled": True, "agile_key": "OTM",
        })
        foreign = self.env["project.task.type"].with_context(active_test=False).search(
            [("project_ids", "=", other.id)], limit=1
        )
        with self.assertRaises(ValidationError):
            self._board([self._group("Foreign", foreign)])

    def test_a_board_has_at_most_eight_columns(self):
        self.assertGreaterEqual(len(self.stages), 1)
        with self.assertRaises(ValidationError):
            self._board([self._group(f"C{index}", self.env["project.task.type"]) for index in range(9)])

    def test_a_column_whose_statuses_are_all_gone_is_left_out(self):
        board = self._board([self._group("Empty", self.env["project.task.type"]), self._group("Real", self.stages[0])])
        self.assertEqual([g["name"] for g in self._options(board)["column_groups"]], ["Real"])

    def test_copy_board_copies_the_columns(self):
        board = self._board([self._group("Work", self.stages[1] | self.stages[2], landing=self.stages[2])])
        copy = self.project.with_user(self.manager).agile_board_copy(board.id)
        columns = self.env["agile.board"].browse(copy["id"]).column_group_ids
        self.assertEqual((columns.name, columns.stage_ids, columns.landing_stage_id), ("Work", self.stages[1] | self.stages[2], self.stages[2]))

    @needs_pro("agile.audit")
    def test_only_managers_change_columns_and_changes_are_audited(self):
        board = self._board([self._group("Work", self.stages[1])])
        with self.assertRaises(AccessError):
            self.env["agile.board.column"].with_user(self.contributor).create({
                "board_id": board.id, "name": "Mine", "stage_ids": [(6, 0, self.stages[0].ids)],
            })
        board.column_group_ids.with_user(self.manager).write({"name": "Work now"})
        texts = self.env["agile.audit"].sudo().search(
            [("project_id", "=", self.project.id), ("area", "=", "boards")], order="id"
        ).mapped("text")
        self.assertIn("Board Merged board: column Work now changed.", texts)
