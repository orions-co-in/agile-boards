from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, new_test_user


class TestAgileSummary(TransactionCase):
    """S-201 to S-204: the Summary page data and its entry points."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, login="sum_manager", groups="project.group_project_manager")
        cls.outsider = new_test_user(cls.env, login="sum_outsider", groups="project.group_project_user")
        cls.project = cls.env["project.project"].with_user(cls.manager).create({
            "name": "Summary project", "privacy_visibility": "employees", "agile_enabled": True,
            "agile_key": "SUM", "agile_method": "scrum",
        })
        cls.env["agile.project.member"].sudo().search([
            ("project_id", "=", cls.project.id), ("user_id", "=", cls.outsider.id)]).unlink()
        cls.today = fields.Date.context_today(cls.project)

    def _issue(self, name, **extra):
        values = {"name": name, "project_id": self.project.id, "description": "Summary issue.", "story_points": 3}
        values.update(extra)
        return self.env["project.task"].with_user(self.manager).create(values)

    def _active_sprint(self):
        sprint = self.env["project.sprint"].with_user(self.manager).create({
            "name": "Sum sprint", "project_id": self.project.id, "date_start": self.today,
            "date_option": "custom", "date_end": self.today + timedelta(days=6),
        })
        return sprint

    def _data(self):
        return self.project.with_user(self.manager).agile_summary_data()

    def test_shape_and_extra_counts(self):
        self._issue("Free", user_ids=[(5, 0, 0)])
        self._issue("Unestimated", story_points_estimated=False, story_points=0)
        data = self._data()
        for key in ("status", "types", "flow", "workload", "epics", "release", "activity", "counts", "pulse" if False else "state"):
            self.assertIn(key, data)
        self.assertGreaterEqual(data["counts"]["unassigned"], 1)
        self.assertGreaterEqual(data["counts"]["unestimated"], 1)
        self.assertEqual(
            [row["status"] for row in data["status"]], ["ready", "progress", "review", "done"]
        )

    def test_status_mix_follows_the_active_sprint(self):
        sprint = self._active_sprint()
        planned = self._issue("In sprint", sprint_id=sprint.id)
        self._issue("Not in sprint")
        sprint.with_user(self.manager).action_confirm_plan()
        sprint.with_user(self.manager).action_start()
        by_status = {row["status"]: row["count"] for row in self._data()["status"]}
        self.assertEqual(by_status["ready"], 1, "only the sprint's issue counts")
        planned.with_user(self.manager).write({"user_ids": [(6, 0, [self.manager.id])]})
        planned.with_user(self.manager).action_agile_start()
        by_status = {row["status"]: row["count"] for row in self._data()["status"]}
        self.assertEqual((by_status["ready"], by_status["progress"]), (0, 1))

    def test_flow_counts_created_and_completed_over_30_days(self):
        issue = self._issue("Flow", user_ids=[(6, 0, [self.manager.id])])
        for step in ("mark_ready", "start", "send_review", "complete"):
            getattr(issue.with_user(self.manager), f"action_agile_{step}")()
        flow = self._data()["flow"]
        self.assertEqual(len(flow["days"]), 30)
        self.assertEqual(flow["days"][-1], fields.Date.to_string(self.today))
        self.assertEqual(sum(flow["created"]), 1)
        self.assertEqual(sum(flow["resolved"]), 1)

    def test_workload_lists_people_and_unassigned(self):
        self._issue("Mine", user_ids=[(6, 0, [self.manager.id])], story_points=5)
        self._issue("Nobody", user_ids=[(5, 0, 0)], story_points=2)
        workload = self._data()["workload"]
        person = next(p for p in workload["people"] if p["id"] == self.manager.id)
        self.assertEqual((person["issues"], person["points"]), (1, 5.0))
        self.assertEqual((workload["unassigned"]["issues"], workload["unassigned"]["points"]), (1, 2.0))

    def test_next_release_is_the_nearest_planned_one(self):
        later = self.env["project.version"].with_user(self.manager).create({
            "name": "v2", "project_id": self.project.id, "release_date": self.today + timedelta(days=30)})
        sooner = self.env["project.version"].with_user(self.manager).create({
            "name": "v1", "project_id": self.project.id, "release_date": self.today + timedelta(days=5)})
        release = self._data()["release"]
        self.assertEqual(release["id"], sooner.id)
        self.assertNotEqual(release["id"], later.id)

    def test_activity_lists_comments_on_the_projects_issues(self):
        issue = self._issue("Talk")
        issue.with_user(self.manager).message_post(body="Hello team", message_type="comment")
        rows = self._data()["activity"]
        self.assertTrue(any(row["text"] == "Hello team" and row["issue_key"] == issue.issue_key for row in rows), rows)

    def test_outsiders_cannot_read_it(self):
        with self.assertRaises(AccessError):
            self.project.with_user(self.outsider).agile_summary_data()

    def test_dashboard_link_opens_summary_for_agile_projects_only(self):
        action = self.project.with_user(self.manager).project_update_all_action()
        self.assertEqual(action.get("tag"), "agile_community.summary")
        plain = self.env["project.project"].with_user(self.manager).create({"name": "Plain dash"})
        action = plain.with_user(self.manager).project_update_all_action()
        self.assertNotEqual(action.get("tag"), "agile_community.summary")
        self.assertEqual(action["res_model"], "project.update")

    def test_unassigned_and_unestimated_tiles_open_their_lists(self):
        free = self._issue("Free list", user_ids=[(5, 0, 0)], story_points_estimated=False, story_points=0)
        for metric, title in (("unassigned", "Unassigned Issues"), ("unestimated", "Unestimated Issues")):
            action = self.project.with_user(self.manager).with_context(
                agile_metric_filter=metric).action_view_agile_metric_issues()
            self.assertEqual(action["name"], title)
            self.assertIn(free, self.env["project.task"].search(action["domain"]))
