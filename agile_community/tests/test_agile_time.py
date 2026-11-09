from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, new_test_user


class TestAgileTime(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, login="tm_manager", groups="project.group_project_manager")
        cls.project = cls.env["project.project"].with_user(cls.manager).create({
            "name": "Time project", "privacy_visibility": "employees", "agile_enabled": True, "agile_key": "TIM",
        })

    def _issue(self, **vals):
        return self.env["project.task"].with_user(self.manager).create({
            "name": "Issue", "project_id": self.project.id, **vals})

    def test_remaining_starts_at_the_estimate_and_falls_with_logged_time(self):
        issue = self._issue(allocated_hours=10.0)
        self.assertEqual((issue.agile_logged_hours, issue.agile_remaining_hours), (0.0, 10.0))
        issue.agile_logged_hours = 4.0
        self.assertEqual(issue.agile_remaining_hours, 6.0)
        self.assertEqual(issue.agile_time_progress, 0.4)
        issue.agile_logged_hours = 12.0
        self.assertEqual(issue.agile_remaining_hours, 0.0, "never below zero")
        self.assertEqual(issue.agile_time_progress, 1.2, "over estimate shows over 100%")

    def test_a_typed_remaining_estimate_stays_until_the_next_change(self):
        issue = self._issue(allocated_hours=10.0)
        issue.agile_logged_hours = 4.0
        issue.agile_remaining_hours = 9.0  # the person re-estimated
        self.assertEqual(issue.agile_remaining_hours, 9.0)
        issue.agile_logged_hours = 5.0
        self.assertEqual(issue.agile_remaining_hours, 5.0, "logging more time recomputes it")

    def test_no_estimate_means_nothing_remaining_and_no_progress_figure(self):
        issue = self._issue()
        issue.agile_logged_hours = 2.0
        self.assertEqual((issue.agile_remaining_hours, issue.agile_time_progress), (0.0, 0.0))

    def test_negative_figures_are_refused(self):
        issue = self._issue(allocated_hours=5.0)
        for field in ("allocated_hours", "agile_logged_hours", "agile_remaining_hours"):
            with self.assertRaises(ValidationError, msg=field):
                issue.write({field: -1.0})

    def test_time_is_copied_as_an_estimate_but_not_as_work_done(self):
        issue = self._issue(allocated_hours=6.0)
        issue.agile_logged_hours = 2.0
        copy = issue.copy()
        self.assertEqual(copy.allocated_hours, 6.0)
        self.assertEqual((copy.agile_logged_hours, copy.agile_remaining_hours), (0.0, 6.0))
