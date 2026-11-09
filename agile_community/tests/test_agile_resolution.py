from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, new_test_user


class TestAgileResolution(TransactionCase):
    """The optional Resolution field (J-1024)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        group = "project.group_project_user"
        cls.manager = new_test_user(cls.env, login="rs_manager", groups="project.group_project_manager", name="Mia Manager")
        cls.contributor = new_test_user(cls.env, login="rs_contrib", groups=group, name="Cora Contributor")
        cls.stakeholder = new_test_user(cls.env, login="rs_stake", groups=group, name="Sam Stakeholder")
        cls.project = cls.env["project.project"].with_user(cls.manager).create({
            "name": "Resolution project", "privacy_visibility": "employees", "agile_enabled": True,
            "agile_key": "RSL", "agile_method": "scrum"})
        Member = cls.env["agile.project.member"].sudo()
        for user, role in ((cls.contributor, "contributor"), (cls.stakeholder, "stakeholder")):
            member = Member.search([("project_id", "=", cls.project.id), ("user_id", "=", user.id)])
            if member:
                member.role = role
            else:
                Member.create({"project_id": cls.project.id, "user_id": user.id, "role": role})

    def _review_issue(self):
        issue = self.env["project.task"].with_user(self.manager).create({
            "name": "Closable", "project_id": self.project.id, "description": "x",
            "user_ids": [Command.set([self.contributor.id])]})
        for step in ("mark_ready", "start", "send_review"):
            getattr(issue.with_user(self.manager), f"action_agile_{step}")()
        return issue

    def _use_resolution(self):
        self.project.with_user(self.manager).agile_use_resolution = True

    def test_off_by_default_so_nothing_changes(self):
        issue = self._review_issue()
        issue.with_user(self.manager).action_agile_complete()
        self.assertFalse(issue.agile_resolution)

    def test_completing_and_canceling_pick_a_default(self):
        self._use_resolution()
        done = self._review_issue()
        done.with_user(self.manager).action_agile_complete()
        self.assertEqual(done.agile_resolution, "done")
        canceled = self._review_issue()
        canceled.with_user(self.manager).action_agile_cancel()
        self.assertEqual(canceled.agile_resolution, "wont_do")

    def test_the_dialog_choice_is_kept_and_reopening_clears_it(self):
        self._use_resolution()
        issue = self._review_issue()
        action = issue.with_user(self.manager).with_context(agile_close="canceled").action_agile_pick_resolution()
        self.assertEqual(action["res_model"], "agile_community.resolution_wizard")
        wizard = self.env["agile_community.resolution_wizard"].with_user(self.manager).create(
            {"task_id": action["context"]["default_task_id"], "kind": action["context"]["default_kind"]})
        self.assertEqual(wizard.resolution, "wont_do", "the default is already chosen")
        wizard.resolution = "duplicate"
        wizard.action_confirm()
        self.assertEqual((issue.agile_status, issue.agile_resolution), ("canceled", "duplicate"))
        issue.with_user(self.manager).action_agile_reopen()
        self.assertFalse(issue.agile_resolution)
        self.assertIn("Resolution", " ".join(issue.sudo().message_ids.tracking_value_ids.mapped("field_id.field_description")))

    def test_a_refused_move_keeps_no_resolution(self):
        self._use_resolution()
        issue = self._review_issue()
        wizard = self.env["agile_community.resolution_wizard"].with_user(self.stakeholder).create(
            {"task_id": issue.id, "kind": "done"})
        with self.assertRaises(Exception):
            wizard.action_confirm()
        self.assertFalse(issue.agile_resolution)

    def test_only_a_manager_turns_it_on(self):
        with self.assertRaises(AccessError):
            self.project.with_user(self.contributor).agile_use_resolution = True

    def test_search_and_query_by_resolution(self):
        from odoo.addons.agile_community.models.agile_query import AgileQuery, QueryError

        self._use_resolution()
        closed = self._review_issue()
        closed.with_user(self.manager).action_agile_complete()
        open_issue = self._review_issue()
        Task = self.env["project.task"].with_user(self.manager)

        def find(text):
            domain, _words = AgileQuery(self.env(user=self.manager), self.project).compile(text)
            return Task.search([("project_id", "=", self.project.id)] + domain)

        self.assertEqual(find("resolution = Done"), closed)
        self.assertEqual(find("resolution IS EMPTY"), open_issue)
        self.assertEqual(find('resolution = "Won\'t do"'), Task.browse())
        with self.assertRaises(QueryError):
            find("resolution = Maybe")

    def test_the_resolution_is_not_copied_by_a_clone(self):
        self._use_resolution()
        issue = self._review_issue()
        issue.with_user(self.manager).action_agile_complete()
        clone = self.env["project.task"].browse(issue.with_user(self.manager).agile_clone("Copy")["id"])
        self.assertFalse(clone.agile_resolution)
