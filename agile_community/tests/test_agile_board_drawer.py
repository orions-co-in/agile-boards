from lxml import etree

from odoo.tests.common import TransactionCase, new_test_user


class TestAgileBoardDrawer(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(
            cls.env, login="agile_drawer_manager", groups="project.group_project_manager"
        )
        cls.contributor = new_test_user(
            cls.env, login="agile_drawer_contributor", groups="project.group_project_user"
        )
        cls.project = cls.env["project.project"].with_user(cls.manager).create({
            "name": "Drawer",
            "privacy_visibility": "employees",
            "agile_enabled": True,
            "agile_key": "DRW",
            "agile_method": "scrum",
        })
        if not cls.env["agile.project.member"].search([
            ("project_id", "=", cls.project.id), ("user_id", "=", cls.contributor.id),
        ]):
            cls.env["agile.project.member"].create({
                "project_id": cls.project.id, "user_id": cls.contributor.id, "role": "contributor",
            })

    def _start_sprint(self):
        sprint = self.env["project.sprint"].with_user(self.manager).create({
            "name": "Now", "project_id": self.project.id, "date_start": "2026-09-01",
        })
        sprint.action_confirm_plan()
        sprint.action_start()
        return sprint

    def test_board_action_names_the_drawer_form(self):
        action = self.project.with_user(self.manager).action_view_tasks()
        drawer = self.env.ref("agile_community.view_project_task_form_agile_drawer")
        self.assertEqual(action["context"]["agile_drawer_view_id"], drawer.id)

    def test_drawer_form_is_compact_and_keeps_the_workflow_buttons(self):
        view = self.env["project.task"].get_view(
            self.env.ref("agile_community.view_project_task_form_agile_drawer").id, "form"
        )
        arch = etree.fromstring(view["arch"])
        for button in ("action_agile_start", "action_agile_complete", "action_agile_reopen"):
            self.assertTrue(arch.xpath("//button[@name='%s']" % button), button)
        # The stage changes only through the workflow buttons.
        stage = arch.xpath("//field[@name='stage_id']")[0]
        self.assertIn(stage.get("readonly"), ("1", "True"))
        self.assertTrue(arch.xpath("//chatter"))
        for name in ("user_ids", "story_points", "parent_id", "description", "date_deadline"):
            self.assertTrue(arch.xpath("//field[@name='%s']" % name), name)

    def test_manager_creates_board_issues_in_the_active_sprint(self):
        sprint = self._start_sprint()
        action = self.project.with_user(self.manager).action_view_tasks()
        self.assertEqual(action["context"]["default_sprint_id"], sprint.id)
        issue = self.env["project.task"].with_user(self.manager).with_context(
            default_sprint_id=sprint.id, default_project_id=self.project.id
        ).create({"name": "From the board"})
        self.assertEqual(issue.sprint_id, sprint)

    def test_contributors_and_boards_without_a_sprint_get_no_default(self):
        before = self.project.with_user(self.manager).action_view_tasks()
        self.assertNotIn("default_sprint_id", before["context"])
        self._start_sprint()
        contributor = self.project.with_user(self.contributor).action_view_tasks()
        self.assertNotIn("default_sprint_id", contributor["context"])
        self.assertEqual(contributor["context"]["search_default_agile_active_sprint"], 1)
