from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, new_test_user


class TestAgileBulkEdit(TransactionCase):
    """S-931: one change on several issues; every issue follows its own rules."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, login="bulk_manager", groups="project.group_project_manager")
        cls.contributor = new_test_user(cls.env, login="bulk_contrib", groups="project.group_project_user")
        cls.project = cls.env["project.project"].with_user(cls.manager).create({
            "name": "Bulk", "privacy_visibility": "employees", "agile_enabled": True,
            "agile_key": "BLK", "agile_method": "scrum", "use_scrum": True,
        })
        cls.env["agile.project.member"].search([
            ("project_id", "=", cls.project.id), ("user_id", "=", cls.contributor.id)]).sudo().role = "contributor"
        today = fields.Date.context_today(cls.project)
        cls.sprint = cls.env["project.sprint"].with_user(cls.manager).create({
            "name": "S1", "project_id": cls.project.id, "date_start": today,
            "date_option": "custom", "date_end": today + timedelta(days=6),
        })
        cls.tag = cls.env["project.tags"].create({"name": "Urgent"})

    def _issue(self, name="Issue"):
        return self.env["project.task"].with_user(self.manager).create({
            "name": name, "project_id": self.project.id, "description": "Body", "story_points": 1,
        })

    def _bulk(self, issues, change, value=None, user=None, **kwargs):
        user = user or self.manager
        return self.env["project.task"].with_user(user).agile_bulk_update(issues.ids, change, value, **kwargs)

    def test_assignee_changes_all_and_undo_restores(self):
        issues = self._issue("A") | self._issue("B")
        earlier = {issue.id: issue.user_ids for issue in issues}
        result = self._bulk(issues, "assignee", self.contributor.id)
        self.assertEqual(sorted(result["changed"]), sorted(issues.ids))
        self.assertEqual(issues.user_ids, self.contributor)
        self.env["project.task"].with_user(self.manager).agile_bulk_restore(result["restore"])
        self.assertTrue(all(issue.user_ids == earlier[issue.id] for issue in issues))

    def test_an_unknown_id_is_listed_as_refused(self):
        """E2E-015: an id that names no issue is reported, and the real issues still change."""
        issue = self._issue("Known")
        result = self.env["project.task"].with_user(self.manager).agile_bulk_update([issue.id, 999999999], "priority", "1")
        self.assertEqual(result["changed"], [issue.id])
        self.assertEqual([r["id"] for r in result["refused"]], [999999999])
        self.assertIn("no issue with this id", result["refused"][0]["reason"])

    def test_assignee_must_be_able_to_work_on_the_project(self):
        outsider = new_test_user(self.env, login="bulk_out", groups="project.group_project_user")
        self.env["agile.project.member"].sudo().search([
            ("project_id", "=", self.project.id), ("user_id", "=", outsider.id)]).unlink()
        with self.assertRaises(UserError):
            self._bulk(self._issue(), "assignee", outsider.id)

    def test_sprint_move_is_for_managers_and_refusals_are_listed_per_issue(self):
        issues = self._issue("A") | self._issue("B")
        result = self._bulk(issues, "sprint", self.sprint.id, user=self.contributor)
        self.assertEqual(result["changed"], [])
        self.assertEqual(len(result["refused"]), 2)
        self.assertIn("Agile Manager", result["refused"][0]["reason"])
        self.assertTrue(result["refused"][0]["key"].startswith("BLK-"))
        self.assertFalse(issues.sprint_id)

    def test_manager_moves_to_a_sprint_and_back_to_the_backlog(self):
        issues = self._issue("A") | self._issue("B")
        result = self._bulk(issues, "sprint", self.sprint.id)
        self.assertEqual(issues.sprint_id, self.sprint)
        self._bulk(issues, "sprint", False)
        self.assertFalse(issues.sprint_id)
        self.env["project.task"].with_user(self.manager).agile_bulk_restore(result["restore"])
        self.assertFalse(issues.sprint_id)

    def test_leaving_a_running_sprint_asks_first(self):
        issue = self._issue()
        issue.write({"sprint_id": self.sprint.id})
        self.sprint.with_user(self.manager).action_confirm_plan()
        self.sprint.with_user(self.manager).action_start()
        asked = self._bulk(issue, "sprint", False)
        self.assertEqual(asked["needs_confirm"], 1)
        self.assertEqual(issue.sprint_id, self.sprint)
        done = self._bulk(issue, "sprint", False, confirmed=True)
        self.assertEqual(done["changed"], issue.ids)
        self.assertFalse(issue.sprint_id)

    def test_status_uses_each_issues_own_workflow_move(self):
        ready = self.env["project.task.type"]._agile_main_stage(self.project, "ready")
        review = self.env["project.task.type"]._agile_main_stage(self.project, "review")
        issues = self._issue("A") | self._issue("B")
        moved = self._bulk(issues, "status", ready.id)
        self.assertEqual(sorted(moved["changed"]), sorted(issues.ids))
        self.assertEqual(issues.stage_id, ready)
        # There is no move from To Do straight to Review.
        refused = self._bulk(issues, "status", review.id)
        self.assertEqual(refused["changed"], [])
        self.assertIn("No move from To Do to Review", refused["refused"][0]["reason"])
        self.assertEqual(refused["restore"], [])

    def test_move_conditions_apply_to_each_issue(self):
        done = self.env["project.task.type"]._agile_main_stage(self.project, "done")
        workflow = self.project.agile_workflow_ids
        workflow.transition_ids.filtered(
            lambda t: t.from_status_id.category == "review" and t.to_status_id.category == "done"
        ).sudo().require_no_open_subtasks = True
        parent, free = self._issue("Parent"), self._issue("Free")
        self.env["project.task"].with_user(self.manager).create({
            "name": "Child", "project_id": self.project.id, "parent_id": parent.id,
            "description": "x", "story_points": 1,
        })
        for issue in (parent, free):
            issue.write({"user_ids": [(6, 0, self.manager.ids)]})
            issue.action_agile_mark_ready()
            issue.action_agile_start()
            issue.action_agile_send_review()
        result = self._bulk(parent | free, "status", done.id)
        self.assertEqual(result["changed"], free.ids)
        self.assertEqual([r["id"] for r in result["refused"]], parent.ids)
        self.assertIn("open sub-issue", result["refused"][0]["reason"])

    def test_labels_add_and_remove(self):
        issues = self._issue("A") | self._issue("B")
        self._bulk(issues, "label_add", self.tag.id)
        self.assertEqual(issues.tag_ids, self.tag)
        result = self._bulk(issues, "label_remove", self.tag.id)
        self.assertFalse(issues.tag_ids)
        self.env["project.task"].with_user(self.manager).agile_bulk_restore(result["restore"])
        self.assertEqual(issues.tag_ids, self.tag)

    def test_limits_and_wrong_input(self):
        Task = self.env["project.task"].with_user(self.manager)
        with self.assertRaises(UserError):
            Task.agile_bulk_update([], "assignee", self.contributor.id)
        with self.assertRaises(UserError):
            Task.agile_bulk_update(list(range(1, 102)), "assignee", self.contributor.id)
        with self.assertRaises(UserError):
            Task.agile_bulk_update(self._issue().ids, "priority", 1)

    def test_issues_of_two_projects_are_refused(self):
        other = self.env["project.project"].with_user(self.manager).create({
            "name": "Other", "privacy_visibility": "employees", "agile_enabled": True, "agile_key": "OTH",
        })
        elsewhere = self.env["project.task"].with_user(self.manager).create({
            "name": "Elsewhere", "project_id": other.id, "description": "x", "story_points": 1,
        })
        with self.assertRaises(UserError):
            self._bulk(self._issue() | elsewhere, "assignee", self.contributor.id)

    def test_type_priority_and_due_date_change_and_undo(self):
        issues = self._issue("A") | self._issue("B")
        issue_type = self.env["agile_community.task_type"].search([("active", "=", True)], limit=1)
        first_priority = issues[0].priority
        result = self._bulk(issues, "type", issue_type.id)
        self.assertEqual(result["changed"], issues.ids)
        self.assertEqual(issues.agile_task_type_id, issue_type)
        self._bulk(issues, "priority", "1")
        self.assertEqual(set(issues.mapped("priority")), {"1"})
        result = self._bulk(issues, "due", "2026-12-24")
        self.assertEqual({d.date().isoformat() for d in issues.mapped("date_deadline")}, {"2026-12-24"})
        self.env["project.task"].with_user(self.manager).agile_bulk_restore(result["restore"])
        self.assertFalse(any(issues.mapped("date_deadline")))
        self._bulk(issues, "due", None)
        self.assertFalse(any(issues.mapped("date_deadline")), "no value clears the due date")
        self.assertEqual(first_priority, "0")

    def test_wrong_type_priority_and_date_are_refused_up_front(self):
        issues = self._issue("A")
        with self.assertRaises(UserError):
            self._bulk(issues, "priority", "9")
        with self.assertRaises(UserError):
            self._bulk(issues, "type", 0)
        with self.assertRaises(UserError):
            self._bulk(issues, "due", "not a date")

    def test_watch_and_unwatch_follow_the_current_user_and_undo(self):
        issues = self._issue("A") | self._issue("B")
        partner = self.manager.partner_id
        issues.message_unsubscribe(partner_ids=partner.ids)
        result = self._bulk(issues, "watch")
        self.assertEqual(result["changed"], issues.ids)
        self.assertTrue(all(partner in issue.message_partner_ids for issue in issues))
        again = self._bulk(issues, "watch")
        self.assertEqual(len(again["refused"]), 2, "already watched")
        self.env["project.task"].with_user(self.manager).agile_bulk_restore(result["restore"])
        self.assertFalse(any(partner in issue.message_partner_ids for issue in issues))
        self._bulk(issues, "watch")
        self.assertEqual(self._bulk(issues, "unwatch")["changed"], issues.ids)

    def test_bulk_options_list_types_and_priorities(self):
        options = self.project.with_user(self.manager).agile_bulk_options()
        self.assertTrue(options["types"])
        self.assertEqual([p["id"] for p in options["priorities"]], ["0", "1", "2", "3"])
