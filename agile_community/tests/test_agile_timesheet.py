from unittest import SkipTest

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged("post_install", "-at_install")
class TestAgileTimesheet(TransactionCase):
    """Only runs when the Timesheets app is installed next to Agile Boards."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if "effective_hours" not in cls.env["project.task"]._fields:
            raise SkipTest("hr_timesheet is not installed")
        cls.user = new_test_user(
            cls.env, login="ts_user", groups="project.group_project_manager,hr_timesheet.group_hr_timesheet_user")
        cls.employee = cls.env["hr.employee"].create({"name": "TS employee", "user_id": cls.user.id})
        cls.project = cls.env["project.project"].with_user(cls.user).create({
            "name": "Timesheet project", "privacy_visibility": "employees", "agile_enabled": True,
            "agile_key": "TSB", "allow_timesheets": True,
        })
        cls.task = cls.env["project.task"].with_user(cls.user).create({
            "name": "Timed", "project_id": cls.project.id, "allocated_hours": 8.0,
        })

    def _log(self, hours):
        return self.env["account.analytic.line"].with_user(self.user).create({
            "name": "Work", "project_id": self.project.id, "task_id": self.task.id,
            "employee_id": self.employee.id, "unit_amount": hours,
        })

    def test_logged_time_and_remaining_follow_the_timesheets(self):
        self.assertEqual(self.task.agile_logged_hours, 0.0)
        line = self._log(3.0)
        self.task.invalidate_recordset()
        self.assertEqual(self.task.agile_logged_hours, 3.0)
        self.assertEqual(self.task.agile_remaining_hours, 5.0)
        self._log(2.5)
        self.task.invalidate_recordset()
        self.assertEqual((self.task.agile_logged_hours, self.task.agile_remaining_hours), (5.5, 2.5))
        line.unlink()
        self.task.invalidate_recordset()
        self.assertEqual((self.task.agile_logged_hours, self.task.agile_remaining_hours), (2.5, 5.5))

    def test_the_logged_figure_cannot_be_typed_when_timesheets_are_used(self):
        self.assertTrue(self.task._fields["agile_logged_hours"].readonly)
        self.assertEqual(self.task._fields["agile_logged_hours"].compute, "_compute_agile_logged_hours")

    def test_logged_work_shows_in_the_history_feed(self):
        self._log(1.5)
        feed = self.task.with_user(self.user).agile_history_feed()
        self.assertTrue(feed["worklog_available"])
        work = [entry for entry in feed["entries"] if entry["kind"] == "worklog"]
        self.assertEqual([entry["hours"] for entry in work], [1.5])

    def _wizard(self, **values):
        return self.env["agile.log.work"].with_user(self.user).with_context(default_task_id=self.task.id).create(
            {"task_id": self.task.id, "hours": 1.5, **values}
        )

    def test_log_work_creates_a_timesheet_line_for_the_person(self):
        self._wizard(description="Pairing").action_log_work()
        line = self.env["account.analytic.line"].search([("task_id", "=", self.task.id)])
        self.assertEqual((line.unit_amount, line.name, line.employee_id), (1.5, "Pairing", self.employee))
        self.task.invalidate_recordset()
        self.assertEqual(self.task.agile_logged_hours, 1.5)

    def test_log_work_needs_a_positive_time(self):
        with self.assertRaises(UserError):
            self._wizard(hours=0).action_log_work()

    def test_log_work_needs_timesheets_on_the_project(self):
        self.project.allow_timesheets = False
        with self.assertRaises(UserError):
            self.task.with_user(self.user).action_agile_log_work()

    def test_a_user_without_an_employee_is_told_to_ask_an_administrator(self):
        stranger = new_test_user(
            self.env, login="ts_stranger", groups="project.group_project_user,hr_timesheet.group_hr_timesheet_user")
        self.env["agile.project.member"].sudo().create(
            {"project_id": self.project.id, "user_id": stranger.id, "role": "contributor"})
        with self.assertRaises(UserError):
            self.task.with_user(stranger).action_agile_log_work()

    def test_a_stakeholder_cannot_log_work(self):
        viewer = new_test_user(
            self.env, login="ts_viewer", groups="project.group_project_user,hr_timesheet.group_hr_timesheet_user")
        self.env["hr.employee"].create({"name": "Viewer", "user_id": viewer.id})
        self.env["agile.project.member"].sudo().create(
            {"project_id": self.project.id, "user_id": viewer.id, "role": "stakeholder"})
        with self.assertRaises(AccessError):
            self.task.with_user(viewer).action_agile_log_work()
