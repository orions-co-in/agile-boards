from odoo.addons.base.tests.common import BaseCommon
from odoo.exceptions import UserError


class TestProjectProject(BaseCommon):
    # Odoo 20 runs these tests as a plain test user, so give it the roles the 19.0 superuser had.
    _test_user_groups = ("base.group_user", "project.group_project_manager", "analytic.group_analytic_accounting")

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user_demo = cls._create_new_internal_user(
            login="scrum_project_user",
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
                "date_start": "2024-08-30",
                "date_end": "2024-09-15",
            }
        )
        cls.task_1 = cls.env["project.task"].create(
            {
                "name": "Test Task 1",
                "project_id": cls.project.id,
                "user_ids": [(4, cls.user_demo.id)],
                "sprint_id": cls.sprint.id,
            }
        )
        cls.task_2 = cls.env["project.task"].create(
            {
                "name": "Test Task 2",
                "project_id": cls.project.id,
                "user_ids": [(4, cls.user_demo.id)],
            }
        )

    def test_backlog_count(self):
        self.project._compute_backlog_count()
        self.assertEqual(self.project.backlog_count, 1)
        self.task_2.sprint_id = self.sprint.id
        self.project._compute_backlog_count()
        self.assertEqual(self.project.backlog_count, 0)

    def test_sprint_count(self):
        self.project._compute_sprint_count()
        self.assertEqual(self.project.sprint_count, 1)

    def test_action_sprints(self):
        action = self.project.action_sprints()
        self.assertEqual(action["res_model"], "project.sprint")
        self.assertEqual(
            action["domain"],
            [("project_id", "=", self.project.id)],
        )
        self.assertEqual(action["context"], {"default_project_id": self.project.id})

    def test_action_backlog(self):
        action = self.project.action_backlog()
        self.assertEqual(action["res_model"], "project.task")
        self.assertEqual(
            action["domain"],
            [
                ("project_id", "=", self.project.id),
                ("sprint_id", "=", False),
                ("state", "!=", "1_done"),
            ],
        )
        self.assertEqual(action["context"], {"default_project_id": self.project.id})

    def test_normal_project_has_no_sprint_navigation(self):
        normal_project = self.env["project.project"].create({"name": "Normal Project"})
        self.assertFalse(normal_project.use_scrum)
        with self.assertRaises(UserError):
            normal_project.action_sprints()
