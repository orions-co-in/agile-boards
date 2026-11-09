from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, new_test_user


class TestAgileBoardDefaults(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(
            cls.env,
            login="agile_board_default_manager",
            groups="project.group_project_manager",
        )
        cls.project = cls.env["project.project"].with_user(cls.manager).create({
            "name": "Board defaults",
            "privacy_visibility": "employees",
            "agile_enabled": True,
            "agile_key": "BRD",
            "agile_method": "scrum",
        })

    def test_scrum_board_defaults_to_active_sprint(self):
        sprint = self.env["project.sprint"].with_user(self.manager).create({
            "name": "Current sprint",
            "project_id": self.project.id,
            "date_start": "2026-09-01",
            "date_end": "2026-09-14",
        })
        sprint.action_confirm_plan()
        sprint.action_start()

        action = self.project.with_user(self.manager).action_view_tasks()
        self.assertEqual(action["context"]["agile_scrum_mode"], True)
        self.assertEqual(
            action["context"]["search_default_agile_active_sprint"], 1
        )

    def test_scrum_without_active_sprint_and_kanban_do_not_force_filter(self):
        action = self.project.with_user(self.manager).action_view_tasks()
        self.assertNotIn(
            "search_default_agile_active_sprint", action["context"]
        )

        self.project.with_user(self.manager).write({"agile_method": "kanban"})
        kanban_action = self.project.with_user(self.manager).action_view_tasks()
        self.assertFalse(kanban_action["context"]["agile_scrum_mode"])
        self.assertNotIn(
            "search_default_agile_active_sprint", kanban_action["context"]
        )

    def _hides_backlog(self, action):
        return ("stage_id.agile_status", "!=", "backlog") in action["domain"]

    def test_kanban_backlog_column_is_off_by_default_and_a_manager_can_turn_it_on(self):
        project = self.project.with_user(self.manager)
        project.write({"agile_method": "kanban"})
        self.assertFalse(project.agile_kanban_backlog_column)
        self.assertTrue(self._hides_backlog(project.action_view_tasks()))
        project.write({"agile_kanban_backlog_column": True})
        self.assertFalse(self._hides_backlog(project.action_view_tasks()))

    def test_scrum_never_shows_a_backlog_column(self):
        project = self.project.with_user(self.manager)
        project.write({"agile_kanban_backlog_column": True})
        self.assertEqual(project.agile_method, "scrum")
        self.assertTrue(self._hides_backlog(project.action_view_tasks()))

    def test_only_an_agile_manager_changes_the_backlog_column(self):
        self.project.with_user(self.manager).write({"agile_method": "kanban"})
        contributor = new_test_user(self.env, login="agile_board_default_contributor", groups="project.group_project_user")
        self.env["agile.project.member"].create({
            "project_id": self.project.id, "user_id": contributor.id, "role": "contributor",
        })
        with self.assertRaises(AccessError):
            self.project.with_user(contributor).write({"agile_kanban_backlog_column": True})

    def _load_tasks_action_from_url(self, user, project):
        """Mimic /web/action/load for /odoo/project/<id>/tasks (sudo, active_id)."""
        action = self.env.ref("project.act_project_project_2_project_task_all")
        return (
            action.with_user(user)
            .sudo()
            .with_context(active_id=project.id)
            ._get_action_dict()
        )

    def test_url_reload_keeps_agile_board_without_open_filter(self):
        loaded = self._load_tasks_action_from_url(self.manager, self.project)
        clicked = self.project.with_user(self.manager).action_view_tasks()

        self.assertEqual(
            loaded["id"],
            self.env.ref("project.act_project_project_2_project_task_all").id,
        )
        self.assertEqual(loaded["path"], "tasks")
        self.assertEqual(loaded["context"], clicked["context"])
        self.assertEqual(loaded["domain"], clicked["domain"])
        self.assertEqual(loaded["views"], clicked["views"])
        self.assertNotIn("search_default_open_tasks", loaded["context"])

    def test_url_reload_uses_real_user_role_not_sudo(self):
        stakeholder = new_test_user(
            self.env,
            login="agile_board_default_stakeholder",
            groups="agile_community.group_agile_stakeholder",
        )
        self.env["agile.project.member"].with_user(self.manager).create({
            "project_id": self.project.id,
            "user_id": stakeholder.id,
            "role": "stakeholder",
        })
        loaded = self._load_tasks_action_from_url(stakeholder, self.project)
        self.assertFalse(loaded["context"]["create"])
        self.assertFalse(loaded["context"]["edit"])

    def test_url_reload_leaves_native_projects_untouched(self):
        native = self.env["project.project"].create({"name": "Native board"})
        loaded = self._load_tasks_action_from_url(self.manager, native)
        self.assertIsInstance(loaded["context"], str)
        self.assertIn("search_default_open_tasks", loaded["context"])
