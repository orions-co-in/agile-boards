from odoo.exceptions import ValidationError

from odoo.addons.base.tests.common import BaseCommon


class TestProjectTask(BaseCommon):
    # Odoo 20 runs these tests as a plain test user, so give it the roles the 19.0 superuser had.
    _test_user_groups = ("base.group_user", "project.group_project_manager", "analytic.group_analytic_accounting")

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user_demo = cls._create_new_internal_user(
            login="scrum_task_user",
            groups="project.group_project_user",
        )
        cls.user_admin = cls.env.ref("base.user_admin")
        cls.project = cls.env["project.project"].create(
            {"name": "Test Project", "user_id": cls.user_demo.id, "use_scrum": True}
        )
        cls.sprint = cls.env["project.sprint"].create(
            {
                "name": "Test Sprint",
                "user_ids": [(4, cls.user_demo.id)],
                "project_id": cls.project.id,
                "date_start": "2021-01-01",
                "date_end": "2021-01-15",
            }
        )
        cls.task = cls.env["project.task"].create(
            {
                "name": "Test Task",
                "project_id": cls.project.id,
                "user_ids": [(4, cls.user_demo.id)],
                "sprint_id": cls.sprint.id,
            }
        )

    def test_story_points_have_an_upper_limit(self):
        """E2E-004: 1e30 points were accepted and stored."""
        self.task.write({"story_points": 10000})
        with self.assertRaises(ValidationError):
            self.task.write({"story_points": 10001})
        with self.assertRaises(ValidationError):
            self.task.write({"story_points": 1e30})
        self.assertEqual(self.task.story_points, 10000)

    def test_sprint_must_match_enabled_project(self):
        other_project = self.env["project.project"].create(
            {"name": "Other Project", "use_scrum": True}
        )
        other_sprint = self.env["project.sprint"].create(
            {
                "name": "Other Sprint",
                "project_id": other_project.id,
                "date_start": "2021-01-01",
                "date_end": "2021-01-15",
            }
        )
        with self.assertRaises(ValidationError):
            self.task.sprint_id = other_sprint

    def test_changing_sprint_does_not_clear_assignees(self):
        self.task.write({"sprint_id": self.sprint.id})
        self.assertEqual(self.task.user_ids, self.user_demo)

    def test_native_project_task_remains_unplanned(self):
        project = self.env["project.project"].create({"name": "Native Project"})
        task = self.env["project.task"].create(
            {"name": "Ordinary task", "project_id": project.id}
        )
        self.assertFalse(project.use_scrum)
        self.assertFalse(task.sprint_id)

    def test_sprint_group_aggregates_issue_points_and_unestimated_count(self):
        self.assertEqual(self.task.sprint_group_points, 0)
        self.assertEqual(self.task.sprint_group_unestimated_count, 1)
        child = self.env["project.task"].create(
            {
                "name": "Child issue",
                "project_id": self.project.id,
                "parent_id": self.task.id,
                "sprint_id": self.sprint.id,
                "story_points": 2,
            }
        )
        self.task.write({"story_points": 8})
        group = self.env["project.task"]._read_group(
            [("sprint_id", "=", self.sprint.id)],
            ["sprint_id"],
            ["__count", "sprint_group_points:sum", "sprint_group_unestimated_count:sum"],
        )[0]
        self.assertEqual(group[1:], (2, 2, 0))

        child.write({"state": "1_canceled", "sprint_id": False})
        self.assertEqual(self.task.sprint_group_points, 8)
        self.assertEqual(child.sprint_group_points, 0)
