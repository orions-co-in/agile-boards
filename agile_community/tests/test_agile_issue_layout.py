from odoo.tests.common import TransactionCase


class TestAgileIssueLayout(TransactionCase):
    """U-1453: the description comes before the time fields on every issue layout."""

    def _arch(self, xmlid=None):
        if xmlid:
            view = self.env.ref(xmlid)
            return self.env["project.task"].get_view(view.id, "form")["arch"]
        return self.env["project.task"].get_view(view_type="form")["arch"]

    def test_drawer_description_before_time_tracking(self):
        arch = self._arch("agile_community.view_project_task_form_agile_drawer")
        self.assertIn('name="description"', arch)
        self.assertLess(arch.index('name="description"'), arch.index('name="allocated_hours"'))

    def test_full_form_description_page_before_time_tracking(self):
        arch = self._arch()
        self.assertIn('name="description_page"', arch)
        self.assertLess(arch.index('name="description_page"'), arch.index('name="agile_time_tracking"'))


class TestAgileLogWorkAndAssign(TransactionCase):
    """U-1457: Assign to me and Log work work without the Timesheets app."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from odoo.tests.common import new_test_user
        cls.manager = new_test_user(cls.env, login="logwork_manager", groups="project.group_project_manager")
        cls.dev = new_test_user(cls.env, login="logwork_dev", groups="project.group_project_user")
        cls.project = cls.env["project.project"].with_user(cls.manager).create({
            "name": "Log work", "agile_enabled": True, "agile_key": "LGW", "agile_method": "kanban",
            "privacy_visibility": "employees",
        })
        cls.task = cls.env["project.task"].with_user(cls.manager).create({
            "name": "Fix it", "project_id": cls.project.id, "user_ids": [(5, 0, 0)],
        })

    def test_assign_to_me_adds_the_current_user(self):
        task = self.task.with_user(self.manager)
        self.assertTrue(task.agile_can_assign_me)
        task.action_agile_assign_to_me()
        self.assertIn(self.manager, task.user_ids)
        self.assertFalse(task.agile_can_assign_me)

    def test_log_work_adds_to_the_total(self):
        if "effective_hours" in self.env["project.task"]._fields:
            self.skipTest("With Timesheets installed, work is logged as timesheet lines")
        task = self.task.with_user(self.manager)
        self.assertTrue(task.agile_log_time_available)
        wizard = self.env["agile.log.time"].with_user(self.manager).with_context(default_task_id=task.id).create({
            "task_id": task.id, "hours": 1.5, "description": "Pairing",
        })
        wizard.action_log_time()
        wizard = self.env["agile.log.time"].with_user(self.manager).with_context(default_task_id=task.id).create({
            "task_id": task.id, "hours": 0.5,
        })
        wizard.action_log_time()
        self.assertEqual(task.agile_logged_hours, 2.0)
        self.assertIn("Pairing", " ".join(task.message_ids.mapped("body")))

    def test_log_work_needs_a_positive_time(self):
        if "effective_hours" in self.env["project.task"]._fields:
            self.skipTest("With Timesheets installed, work is logged as timesheet lines")
        from odoo.exceptions import UserError
        task = self.task.with_user(self.manager)
        wizard = self.env["agile.log.time"].with_user(self.manager).with_context(default_task_id=task.id).create({
            "task_id": task.id, "hours": 0,
        })
        with self.assertRaises(UserError):
            wizard.action_log_time()
