from lxml import etree

from odoo.tests.common import TransactionCase, new_test_user


class TestAgileBoard(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(
            cls.env,
            login="agile_board_manager",
            groups="project.group_project_manager",
        )
        cls.project = cls.env["project.project"].with_user(cls.manager).create({
            "name": "Board",
            "privacy_visibility": "employees",
            "agile_enabled": True,
            "agile_key": "BOA",
            "agile_method": "scrum",
        })

    def _sprint(self, **vals):
        values = {
            "name": "Sprint",
            "project_id": self.project.id,
            "date_start": "2026-09-01",
        }
        values.update(vals)
        return self.env["project.sprint"].with_user(self.manager).create(values)

    def test_board_actions_keep_epic_children_visible(self):
        # Core hides sub-tasks unless this flag is set; epic children are issues.
        action = self.project.with_user(self.manager).action_view_tasks()
        self.assertTrue(action["context"]["subtask_action"])
        sprint = self._sprint()
        self.assertTrue(sprint.with_user(self.manager).action_tasks()["context"]["subtask_action"])

    def test_board_shows_every_workflow_column(self):
        Task = self.env["project.task"].with_context(
            default_project_id=self.project.id,
            agile_project_view=True,
            subtask_action=True,
        )
        project_stages = self.env["project.task.type"].search(
            [("project_ids", "=", self.project.id)]
        )
        self.assertGreater(len(project_stages), 1)
        expanded = Task._read_group_stage_ids(self.env["project.task.type"], [])
        self.assertEqual(set(project_stages.ids), set(expanded.ids))

    def test_other_views_keep_core_column_rules(self):
        Task = self.env["project.task"].with_context(default_project_id=self.project.id)
        stages = self.env["project.task.type"].search(
            [("project_ids", "=", self.project.id)], limit=1
        )
        expanded = Task._read_group_stage_ids(stages, [])
        self.assertEqual(expanded, stages)

    def test_card_shows_points_once_and_no_rank_buttons(self):
        view = self.env["project.task"].get_view(
            self.env.ref("agile_community.project_task_kanban_agile_backlog_order").id,
            "kanban",
        )
        arch = etree.fromstring(view["arch"])
        card = arch.xpath("//t[@t-name='card']")[0]
        shown_points = [
            node
            for node in card.xpath(".//field[@name='story_points']")
            if node.get("invisible") != "1"
        ]
        # The estimate is one labelled span ("3 pts"), not a bare field value (UX-5).
        self.assertEqual(shown_points, [])
        self.assertEqual(len(card.xpath(".//span[contains(@class, 'o_ag_card_points')]")), 1)
        self.assertFalse(card.xpath(".//button[@name='action_agile_move_backlog_up']"))
        self.assertFalse(card.xpath(".//button[@name='action_agile_move_backlog_down']"))
        self.assertTrue(card.xpath(".//button[@name='action_agile_mark_ready']"))

    def test_board_uses_the_board_view_class(self):
        view = self.env["project.task"].get_view(
            self.env.ref("agile_community.project_task_kanban_agile_backlog_order").id,
            "kanban",
        )
        self.assertEqual(etree.fromstring(view["arch"]).get("js_class"), "agile_board_kanban")

    def test_end_date_that_disagrees_with_length_makes_a_custom_sprint(self):
        sprint = self._sprint(date_option="1_weeks", date_end="2026-09-15")
        self.assertEqual(sprint.date_option, "custom")
        self.assertEqual(str(sprint.date_end), "2026-09-15")

    def test_end_date_that_matches_the_length_keeps_it(self):
        sprint = self._sprint(date_option="2_weeks", date_end="2026-09-15")
        self.assertEqual(sprint.date_option, "2_weeks")
        self.assertEqual(str(sprint.date_end), "2026-09-15")

    def test_length_alone_still_sets_the_end_date(self):
        sprint = self._sprint(date_option="1_weeks")
        self.assertEqual(sprint.date_option, "1_weeks")
        self.assertEqual(str(sprint.date_end), "2026-09-08")

    def test_writing_a_different_end_date_makes_it_custom(self):
        sprint = self._sprint(date_option="1_weeks")
        sprint.with_user(self.manager).write({"date_end": "2026-09-20"})
        self.assertEqual(sprint.date_option, "custom")
        self.assertEqual(str(sprint.date_end), "2026-09-20")

    def test_choosing_custom_with_an_end_date_is_left_alone(self):
        sprint = self._sprint(date_option="custom", date_end="2026-09-10")
        self.assertEqual(sprint.date_option, "custom")
        sprint.with_user(self.manager).write({"date_end": "2026-09-12"})
        self.assertEqual(str(sprint.date_end), "2026-09-12")

    def test_sprint_form_hides_planning_notes_outside_planning(self):
        view = self.env["project.sprint"].get_view(
            self.env.ref("agile_scrum.project_sprint_view_form").id, "form"
        )
        arch = etree.fromstring(view["arch"])
        for field_name in ("over_capacity", "planning_stale"):
            alert = arch.xpath(
                "//div[@role='alert'][contains(@invisible, '%s')]" % field_name
            )[0]
            self.assertIn("state != 'draft'", alert.get("invisible"))
        note = arch.xpath("//div[@role='note'][contains(., 'Confirming records')]")[0]
        self.assertEqual(note.get("invisible"), "state != 'draft'")
