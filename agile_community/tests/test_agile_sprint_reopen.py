from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user
from .pro_guard import needs_pro


class TestAgileSprintReopen(TransactionCase):
    """R-1106: a manager reopens the latest completed sprint; the plan stays."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, login="reopen_manager", groups="project.group_project_manager")
        cls.contributor = new_test_user(cls.env, login="reopen_contributor", groups="project.group_project_user")
        cls.project = cls.env["project.project"].with_user(cls.manager).create({
            "name": "Reopen", "agile_enabled": True, "agile_key": "RPN", "agile_method": "scrum",
            "privacy_visibility": "employees",
        })
        cls.project.agile_member_ids.filtered(lambda m: m.user_id == cls.contributor).role = "contributor"
        cls.today = fields.Date.context_today(cls.env["project.sprint"])

    def _sprint(self, name, offset, length=6, user=None):
        return self.env["project.sprint"].with_user(user or self.manager).create({
            "name": name, "project_id": self.project.id,
            "date_start": self.today + timedelta(days=offset), "date_option": "custom",
            "date_end": self.today + timedelta(days=offset + length),
        })

    def _complete(self, sprint, issue=None):
        if issue:
            issue.write({"sprint_id": sprint.id})
        sprint.action_confirm_plan()
        sprint.action_start()
        if issue:
            issue = issue.with_user(self.manager)
            for step in ("mark_ready", "start", "send_review", "complete"):
                getattr(issue, f"action_agile_{step}")()
        sprint.action_done()
        return sprint

    def _issue(self, points=3):
        return self.env["project.task"].with_user(self.manager).create({
            "name": "Work", "project_id": self.project.id, "story_points": points,
            "description": "Work that needs doing.",
        })

    @needs_pro("agile.audit")
    def test_reopen_keeps_the_plan_clears_the_totals_and_audits(self):
        sprint = self._complete(self._sprint("S1", -14), self._issue())
        self.assertEqual(sprint.state, "done")
        self.assertTrue(sprint.completed_points)
        revisions = len(sprint.commitment_ids)
        self.assertTrue(sprint.can_reopen_sprint)

        sprint.agile_reopen("Closed by mistake")

        self.assertEqual(sprint.state, "in_progress")
        self.assertEqual(len(sprint.commitment_ids), revisions)  # no new plan revision
        self.assertTrue(sprint.planning_confirmed)
        self.assertEqual((sprint.completed_points, sprint.committed_points_at_close, sprint.completed_task_count), (0, 0, 0))
        self.assertFalse(sprint.close_summary)
        self.assertEqual(sprint.reopen_count, 1)
        audit = self.env["agile.audit"].sudo().search([("project_id", "=", self.project.id), ("area", "=", "sprints")])
        self.assertEqual(len(audit), 1)
        self.assertIn("Closed by mistake", audit.text)
        self.assertIn("Closed by mistake", " ".join(sprint.message_ids.mapped("body")))

    def test_completing_again_counts_the_totals_from_the_standing_plan(self):
        sprint = self._complete(self._sprint("S1", -14), self._issue(points=5))
        before = (sprint.completed_points, sprint.committed_points_at_close)
        sprint.agile_reopen("One more look")
        sprint.action_done()
        self.assertEqual(sprint.state, "done")
        self.assertEqual((sprint.completed_points, sprint.committed_points_at_close), before)

    def test_a_reason_is_required(self):
        sprint = self._complete(self._sprint("S1", -14))
        for reason in ("", "   ", "no"):
            with self.assertRaises(ValidationError):
                sprint.agile_reopen(reason)
        self.assertEqual(sprint.state, "done")

    def test_only_a_manager_can_reopen(self):
        sprint = self._complete(self._sprint("S1", -14))
        as_contributor = sprint.with_user(self.contributor)
        self.assertFalse(as_contributor.can_reopen_sprint)
        with self.assertRaises(UserError):  # AccessError is a UserError
            as_contributor.agile_reopen("Not allowed to")
        self.assertEqual(sprint.state, "done")

    def test_a_later_sprint_that_started_blocks_it(self):
        first = self._complete(self._sprint("S1", -20))
        second = self._sprint("S2", -10)
        self.assertTrue(first.can_reopen_sprint)
        self._complete(second)
        self.assertFalse(first.can_reopen_sprint)
        with self.assertRaises(UserError):
            first.agile_reopen("Too late now")
        # The latest completed sprint can still be reopened.
        self.assertTrue(second.can_reopen_sprint)

    def test_a_planned_later_sprint_does_not_block_it(self):
        first = self._complete(self._sprint("S1", -20))
        self._sprint("S2", 10)
        self.assertTrue(first.can_reopen_sprint)

    def test_another_active_sprint_blocks_it_unless_several_are_allowed(self):
        first = self._complete(self._sprint("S1", -20))
        second = self._sprint("S2", -5)
        second.action_confirm_plan()
        second.action_start()
        self.assertTrue(first.sudo().date_start < second.date_start)
        self.assertFalse(first.can_reopen_sprint)
        with self.assertRaises(UserError):
            first.agile_reopen("Two at once")

    def test_only_a_completed_sprint_can_be_reopened(self):
        sprint = self._sprint("S1", 3)
        self.assertFalse(sprint.can_reopen_sprint)
        with self.assertRaises(UserError):
            sprint.agile_reopen("Still planned")

    def test_the_dialog_reopens_through_the_wizard(self):
        sprint = self._complete(self._sprint("S1", -14))
        action = sprint.action_agile_open_reopen()
        self.assertEqual(action["res_model"], "agile.sprint.reopen")
        wizard = self.env["agile.sprint.reopen"].with_user(self.manager).create({
            "sprint_id": sprint.id, "reason": "Reopened from the dialog",
        })
        wizard.action_reopen()
        self.assertEqual(sprint.state, "in_progress")

    def test_the_backlog_reports_reopening(self):
        sprint = self._complete(self._sprint("S1", -14))
        rows = {row["id"]: row for row in self.project.with_user(self.manager).agile_backlog_sprints()["sprints"]}
        self.assertTrue(rows[sprint.id]["can_reopen"])
        sprint.agile_reopen("Check the backlog")
        rows = {row["id"]: row for row in self.project.with_user(self.manager).agile_backlog_sprints()["sprints"]}
        self.assertEqual(rows[sprint.id]["reopen_count"], 1)
