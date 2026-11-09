from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, new_test_user

from odoo.addons.agile_community.models.agile_query import AgileQuery
from .pro_guard import needs_pro


class TestAgileMoveProject(TransactionCase):
    """S-1126: a guided move to another project, with status mapping and a redirecting old key."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, login="mv_manager", groups="project.group_project_manager")
        Project = cls.env["project.project"].with_user(cls.manager)
        cls.source = Project.create({"name": "Source", "agile_enabled": True, "agile_key": "SRC", "agile_method": "scrum"})
        cls.target = Project.create({"name": "Target", "agile_enabled": True, "agile_key": "TGT", "agile_method": "kanban"})
        cls.dev = new_test_user(cls.env, login="mv_dev", groups="project.group_project_user")
        cls.env["agile.project.member"].sudo().search([("project_id", "=", cls.source.id), ("user_id", "=", cls.dev.id)]).unlink()
        cls.env["agile.project.member"].sudo().create({"project_id": cls.source.id, "user_id": cls.dev.id, "role": "contributor"})
        cls.env["agile.project.member"].sudo().search([("project_id", "=", cls.target.id), ("user_id", "=", cls.dev.id)]).unlink()
        cls.issue = cls.env["project.task"].with_user(cls.manager).create({"name": "Mover", "project_id": cls.source.id})
        cls.old_key = cls.issue.issue_key

    def _wizard(self, task=None, **values):
        task = task or self.issue
        return self.env["agile.move.project"].with_user(self.manager).with_context(default_task_id=task.id).create(
            {"task_id": task.id, "target_project_id": self.target.id, **values}
        )

    def _move(self, task=None, **values):
        wizard = self._wizard(task, **values)
        wizard.action_next()
        wizard.action_next()
        wizard.action_move()
        return wizard

    def test_the_issue_gets_a_new_key_and_keeps_the_old_one_as_a_redirect(self):
        self._move()
        self.assertEqual(self.issue.project_id, self.target)
        self.assertTrue(self.issue.issue_key.startswith("TGT-"))
        self.assertEqual(self.issue.agile_old_key_ids.key, self.old_key)
        found = self.env["project.task"].with_user(self.manager).name_search(self.old_key)
        self.assertIn(self.issue.id, [row[0] for row in found])

    def test_the_old_key_still_works_in_the_query_language(self):
        self._move()
        query = AgileQuery(self.env(user=self.manager), self.target)
        domain, _words = query.compile('key = "%s"' % self.old_key)
        self.assertEqual(self.env["project.task"].with_user(self.manager).search(domain), self.issue)

    def test_statuses_are_matched_by_name_and_can_be_changed(self):
        ready = self.source.type_ids.filtered(lambda s: s.agile_status == "ready")[:1]
        self.issue.sudo().write({"stage_id": ready.id})
        wizard = self._wizard()
        wizard.action_next()
        line = wizard.line_ids
        self.assertEqual(line.source_stage_id, ready)
        self.assertTrue(line.target_stage_id)
        self.assertEqual(line.target_stage_id.agile_status, "ready")
        wizard.action_next()
        wizard.action_move()
        self.assertIn(self.issue.stage_id, self.target.type_ids)
        self.assertEqual(self.issue.stage_id.agile_status, "ready")

    def test_next_needs_a_project_and_every_status_mapped(self):
        wizard = self.env["agile.move.project"].with_user(self.manager).with_context(default_task_id=self.issue.id).create({"task_id": self.issue.id})
        with self.assertRaises(UserError):
            wizard.action_next()
        wizard.target_project_id = self.target
        wizard.action_next()
        wizard.line_ids.target_stage_id = False
        with self.assertRaises(UserError):
            wizard.action_next()

    def test_sprint_release_and_component_are_dropped_when_the_target_has_no_match(self):
        component = self.env["agile.project.component"].with_user(self.manager).create({"name": "Web", "project_id": self.source.id})
        self.issue.sudo().write({"agile_component_id": component.id})
        wizard = self._wizard()
        self.assertIn("Web", wizard.sudo()._notes()[0] + "".join(wizard.sudo()._notes()))
        wizard.action_next()
        wizard.action_next()
        wizard.action_move()
        self.assertFalse(self.issue.agile_component_id)
        self.assertFalse(self.issue.sprint_id)

    def test_a_component_with_the_same_name_is_kept(self):
        mine = self.env["agile.project.component"].with_user(self.manager).create({"name": "Web", "project_id": self.source.id})
        theirs = self.env["agile.project.component"].with_user(self.manager).create({"name": "Web", "project_id": self.target.id})
        self.issue.sudo().write({"agile_component_id": mine.id})
        self._move()
        self.assertEqual(self.issue.agile_component_id, theirs)

    def test_sub_issues_block_the_move_unless_they_move_too(self):
        child = self.env["project.task"].with_user(self.manager).create({"name": "Child", "project_id": self.source.id, "parent_id": self.issue.id})
        wizard = self._wizard(move_subtasks=False)
        with self.assertRaises(UserError):
            wizard.action_next()
        self._move()
        self.assertEqual(child.project_id, self.target)
        self.assertEqual(child.parent_id, self.issue)
        self.assertTrue(child.issue_key.startswith("TGT-"))

    def test_an_issue_in_an_active_sprint_cannot_move(self):
        sprint = self.env["project.sprint"].sudo().create({"name": "S1", "project_id": self.source.id})
        self.issue.sudo().write({"sprint_id": sprint.id})
        self.env.cr.execute("UPDATE project_sprint SET state = 'in_progress' WHERE id = %s", [sprint.id])
        sprint.invalidate_recordset()
        self.issue.invalidate_recordset()
        with self.assertRaises(UserError):
            self._wizard().action_next()

    def test_a_restricted_issue_cannot_move_to_a_team_that_lacks_its_people(self):
        self.issue.sudo().write({"agile_restricted": True, "agile_visible_user_ids": [(6, 0, self.dev.ids)]})
        with self.assertRaises(UserError):
            self._wizard().action_next()

    @needs_pro("agile.move.approval")
    def test_a_pending_approval_blocks_the_move(self):
        self.issue.sudo().agile_approval_ids.create({
            "task_id": self.issue.id, "to_stage_id": self.source.type_ids[0].id, "requester_id": self.manager.id,
            "expires_on": "2099-01-01 00:00:00",
        })
        with self.assertRaises(UserError):
            self._wizard().action_next()

    def test_only_a_manager_of_the_project_can_start_a_move(self):
        with self.assertRaises(AccessError):
            self.issue.with_user(self.dev).action_agile_move_project()

    def test_assignees_who_are_not_on_the_new_team_are_dropped(self):
        self.issue.sudo().write({"user_ids": [(6, 0, self.dev.ids)]})
        self._move()
        self.assertNotIn(self.dev, self.issue.user_ids)

    def test_comments_and_links_stay_with_the_issue(self):
        self.issue.with_user(self.manager).message_post(body="Keep me")
        self._move()
        self.assertTrue(self.issue.message_ids.filtered(lambda m: "Keep me" in (m.body or "")))
        self.assertTrue(self.issue.message_ids.filtered(lambda m: "moved this issue" in (m.body or "")))
