from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase, new_test_user


class TestAgileSprintDefaults(TransactionCase):
    """NU-04: a new sprint starts after the project's latest one."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, login="sprintdef_manager", groups="project.group_project_manager")
        cls.project = cls.env["project.project"].with_user(cls.manager).create({
            "name": "Sprint defaults", "agile_enabled": True, "agile_key": "SDF", "agile_method": "scrum",
            "privacy_visibility": "employees",
        })
        cls.today = fields.Date.context_today(cls.env["project.sprint"])

    def _default_start(self):
        sprint = self.env["project.sprint"].with_user(self.manager).with_context(default_project_id=self.project.id)
        return sprint.default_get(["date_start"])["date_start"]

    def _add(self, name):
        return self.env["project.sprint"].with_user(self.manager).create({
            "name": name, "project_id": self.project.id, "date_start": self._default_start(),
        })

    def test_first_sprint_starts_today(self):
        self.assertEqual(self._default_start(), self.today)

    def test_next_sprints_do_not_overlap(self):
        first = self._add("One")
        second = self._add("Two")
        third = self._add("Three")
        self.assertEqual(second.date_start, first.date_end + timedelta(days=1))
        self.assertEqual(third.date_start, second.date_end + timedelta(days=1))

    def test_quick_add_twice_from_the_backlog_keeps_the_dates_valid(self):
        """NU-31: "Add a Sprint" sends only a name; the project comes from the context."""
        sprint = self.env["project.sprint"].with_user(self.manager).with_context(default_project_id=self.project.id)
        first = sprint.browse(sprint.name_create("Quick one")[0])
        second = sprint.browse(sprint.name_create("Quick two")[0])
        self.assertEqual(second.date_start, first.date_end + timedelta(days=1))
        self.assertGreaterEqual(second.date_end, second.date_start)

    def test_a_sprint_that_ended_in_the_past_does_not_push_into_the_past(self):
        self.env["project.sprint"].with_user(self.manager).create({
            "name": "Old", "project_id": self.project.id, "date_option": "custom",
            "date_start": self.today - timedelta(days=30), "date_end": self.today - timedelta(days=20),
        })
        self.assertEqual(self._default_start(), self.today)


class TestAgileSprintStartDialog(TransactionCase):
    """NU-05: Start sprint opens a dialog with goal and warnings."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, login="sprintstart_manager", groups="project.group_project_manager")
        cls.contributor = new_test_user(cls.env, login="sprintstart_user", groups="project.group_project_user")
        cls.project = cls.env["project.project"].with_user(cls.manager).create({
            "name": "Start dialog", "agile_enabled": True, "agile_key": "SDG", "agile_method": "scrum",
            "privacy_visibility": "employees",
        })
        cls.today = fields.Date.context_today(cls.env["project.sprint"])
        cls.sprint = cls.env["project.sprint"].with_user(cls.manager).create({
            "name": "Sprint A", "project_id": cls.project.id, "date_start": cls.today + timedelta(days=7),
            "date_option": "custom", "date_end": cls.today + timedelta(days=14),
        })

    def test_dialog_needs_a_confirmed_plan(self):
        from odoo.exceptions import UserError
        with self.assertRaises(UserError):
            self.sprint.with_user(self.manager).action_agile_open_start()

    def test_dialog_warns_about_a_future_start_and_saves_goal_and_dates(self):
        self.sprint.with_user(self.manager).action_confirm_plan()
        action = self.sprint.with_user(self.manager).action_agile_open_start()
        wizard = self.env["agile.sprint.start.wizard"].with_user(self.manager).browse(action["res_id"])
        self.assertIn("future", wizard.warning)
        wizard.write({"goal": "Ship login", "date_start": self.today, "date_end": self.today + timedelta(days=9)})
        self.assertFalse(wizard.warning)
        wizard.action_start_sprint()
        self.assertEqual(self.sprint.state, "in_progress")
        self.assertEqual(self.sprint.description, "Ship login")
        self.assertEqual(self.sprint.date_start, self.today)
        self.assertEqual(self.sprint.date_end, self.today + timedelta(days=9))

    def test_end_before_start_is_refused(self):
        from odoo.exceptions import UserError
        self.sprint.with_user(self.manager).action_confirm_plan()
        action = self.sprint.with_user(self.manager).action_agile_open_start()
        wizard = self.env["agile.sprint.start.wizard"].with_user(self.manager).browse(action["res_id"])
        wizard.date_end = wizard.date_start - timedelta(days=1)
        with self.assertRaises(UserError):
            wizard.action_start_sprint()

    def test_a_contributor_cannot_open_the_dialog(self):
        from odoo.exceptions import AccessError, UserError
        self.sprint.with_user(self.manager).action_confirm_plan()
        with self.assertRaises(Exception) as caught:
            self.sprint.with_user(self.contributor).action_agile_open_start()
        self.assertIsInstance(caught.exception, (AccessError, UserError))


class TestAgileKeyStyle(TransactionCase):
    """NU-17: plain keys (FIT-1) for teams that expect them."""

    def test_plain_style_gives_unpadded_keys_and_old_keys_stay(self):
        manager = new_test_user(self.env, login="keystyle_manager", groups="project.group_project_manager")
        project = self.env["project.project"].with_user(manager).create({
            "name": "Key style", "agile_enabled": True, "agile_key": "KST", "agile_method": "kanban",
            "privacy_visibility": "employees",
        })
        first = self.env["project.task"].with_user(manager).create({"name": "One", "project_id": project.id})
        self.assertEqual(first.issue_key, "KST-0001")
        project.with_user(manager).agile_key_style = "plain"
        second = self.env["project.task"].with_user(manager).create({"name": "Two", "project_id": project.id})
        self.assertEqual(second.issue_key, "KST-2")
        self.assertEqual(first.issue_key, "KST-0001")


class TestAgileSidebarSprintLabel(TransactionCase):
    """U-1456: the sidebar's sprint label follows the sprint's state."""

    def test_label_clears_when_the_sprint_closes(self):
        manager = new_test_user(self.env, login="sidelabel_manager", groups="project.group_project_manager")
        project = self.env["project.project"].with_user(manager).create({
            "name": "Sidebar label", "agile_enabled": True, "agile_key": "SLB", "agile_method": "scrum",
            "privacy_visibility": "employees",
        })
        sprint = self.env["project.sprint"].with_user(manager).create({"name": "Sprint A", "project_id": project.id})
        sprint.with_user(manager).action_confirm_plan()
        sprint.with_user(manager).action_start()
        self.assertEqual(project.with_user(manager).agile_sidebar_data()["sprint"], "Sprint A")
        sprint.with_user(manager).write({"state": "done"})
        self.assertFalse(project.with_user(manager).agile_sidebar_data()["sprint"])

    def test_backlog_badge_counts_leaf_issues_like_the_list(self):
        """NU-32: a story with sub-tasks is not a backlog row, so it is not in the badge either."""
        manager = new_test_user(self.env, login="sidebadge_manager", groups="project.group_project_manager")
        project = self.env["project.project"].with_user(manager).create({
            "name": "Badge", "agile_enabled": True, "agile_key": "BDG", "agile_method": "scrum",
            "privacy_visibility": "employees",
        })
        Task = self.env["project.task"].with_user(manager)
        parent = Task.create({"name": "Parent", "project_id": project.id, "user_ids": [(5, 0, 0)]})
        Task.create({"name": "Child", "project_id": project.id, "parent_id": parent.id, "user_ids": [(5, 0, 0)]})
        Task.create({"name": "Alone", "project_id": project.id, "user_ids": [(5, 0, 0)]})
        self.assertEqual(project.with_user(manager).agile_sidebar_data()["counts"]["backlog"], 2)
