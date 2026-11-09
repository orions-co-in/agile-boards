from odoo import Command
from odoo.tests.common import TransactionCase, new_test_user


class TestAgilePalette(TransactionCase):
    """The command palette's server side (K-1032): go to an issue, recent issues, nothing hidden."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        group = "project.group_project_user"
        cls.manager = new_test_user(cls.env, login="pl_manager", groups="project.group_project_manager")
        cls.alice = new_test_user(cls.env, login="pl_alice", groups=group, name="Alice Palette")
        cls.bob = new_test_user(cls.env, login="pl_bob", groups=group, name="Bob Palette")
        cls.project = cls.env["project.project"].with_user(cls.manager).create({
            "name": "Palette project", "privacy_visibility": "employees", "agile_enabled": True, "agile_key": "PAL",
        })
        cls.other = cls.env["project.project"].with_user(cls.manager).create({
            "name": "Other project", "privacy_visibility": "employees", "agile_enabled": True, "agile_key": "OTH",
        })
        Task = cls.env["project.task"].with_user(cls.manager)
        cls.login = Task.create({"name": "Login page", "project_id": cls.project.id,
                                 "user_ids": [Command.set([cls.alice.id])]})
        cls.secret = Task.create({
            "name": "Secret plan", "project_id": cls.project.id, "agile_restricted": True,
            "user_ids": [Command.set([cls.manager.id])]})
        cls.elsewhere = Task.create({"name": "Login elsewhere", "project_id": cls.other.id})

    def _search(self, term, user=None, project=None):
        env = self.env(user=user) if user else self.env
        return env["project.task"].agile_palette_search(term, (project or self.project).id)

    def test_a_key_opens_the_issue_in_any_readable_project(self):
        found = self._search(self.elsewhere.issue_key.lower(), self.alice)
        self.assertEqual([row["id"] for row in found], [self.elsewhere.id])
        self.assertEqual(found[0]["project"], "Other project")
        self.assertEqual(found[0]["key"], self.elsewhere.issue_key)

    def test_a_short_key_matches_the_zero_padded_one(self):
        number = int(self.login.issue_key.rsplit("-", 1)[1])
        short = f"{self.login.issue_key.rsplit('-', 1)[0]}-{number}"
        self.assertEqual([r["id"] for r in self._search(short, self.alice)], [self.login.id])

    def test_words_find_titles_here_first_then_in_other_projects(self):
        found = self._search("login", self.alice)
        self.assertEqual([row["id"] for row in found], [self.login.id, self.elsewhere.id])
        self.assertEqual([row["project"] for row in found], ["Palette project", "Other project"])
        self.assertEqual(found[1]["project_id"], self.other.id)
        self.assertEqual(self._search("  ", self.alice), [])

    def test_other_projects_need_two_characters_and_are_listed_once(self):
        self.assertEqual([r["id"] for r in self._search("l", self.alice)], [self.login.id],
                         "one letter stays in the open project")
        keys = [r["id"] for r in self._search(self.elsewhere.issue_key, self.alice)]
        self.assertEqual(keys, [self.elsewhere.id], "a key found by its exact match is not repeated")

    def test_a_project_the_person_cannot_read_is_never_searched(self):
        Task = self.env["project.task"].with_user(self.manager)
        private = self.env["project.project"].with_user(self.manager).create({
            "name": "Private project", "privacy_visibility": "followers", "agile_enabled": True, "agile_key": "PRV"})
        hidden = Task.create({"name": "Login private", "project_id": private.id})
        self.assertIn(hidden.id, [r["id"] for r in self._search("login", self.manager)])
        self.assertNotIn(hidden.id, [r["id"] for r in self._search("login", self.alice)])
        self.assertEqual(self._search(hidden.issue_key, self.alice), [])

    def test_a_restricted_issue_is_never_found_or_confirmed(self):
        hidden = self._search(self.secret.issue_key, self.bob)
        missing = self._search("PAL-99999", self.bob)
        self.assertEqual(hidden, missing, "a hidden key answers exactly like a missing one")
        self.assertEqual(hidden, [])
        self.assertEqual(self._search("secret", self.bob), [])
        self.assertEqual([r["id"] for r in self._search("secret", self.manager)], [self.secret.id])

    def test_visits_are_listed_newest_first_per_person_and_capped(self):
        Task = self.env["project.task"].with_user(self.manager)
        tasks = Task.create([{"name": f"Visit {i}", "project_id": self.project.id} for i in range(12)])
        for task in tasks:
            self.assertTrue(task.with_user(self.alice).agile_palette_visit())
        self.login.with_user(self.alice).agile_palette_visit()
        recent = self.env["project.task"].with_user(self.alice).agile_palette_recent(self.project.id)
        self.assertEqual(len(recent), 10, "the last 10 viewed issues")
        self.assertEqual(recent[0]["id"], self.login.id)
        self.assertEqual(recent[1]["id"], tasks[-1].id)
        self.assertFalse(self.env["project.task"].with_user(self.bob).agile_palette_recent(self.project.id),
                         "each person has their own list")
        self.login.with_user(self.alice).agile_palette_visit()
        self.assertEqual(self.env["agile.recent.issue"].sudo().search_count(
            [("user_id", "=", self.alice.id), ("task_id", "=", self.login.id)]), 1, "an issue is listed once")

    def test_recent_never_lists_an_issue_that_became_unreadable(self):
        self.assertTrue(self.secret.with_user(self.manager).agile_palette_visit())
        self.assertFalse(self.secret.with_user(self.bob).agile_palette_visit(), "nothing is recorded for a hidden issue")
        self.env["agile.recent.issue"].sudo().create({
            "user_id": self.bob.id, "task_id": self.secret.id, "project_id": self.project.id})
        self.assertEqual(self.env["project.task"].with_user(self.bob).agile_palette_recent(self.project.id), [])
        self.assertEqual(
            [r["id"] for r in self.env["project.task"].with_user(self.manager).agile_palette_recent(self.project.id)],
            [self.secret.id])

    def test_people_cannot_read_each_others_visits(self):
        self.login.with_user(self.alice).agile_palette_visit()
        rows = self.env["agile.recent.issue"].with_user(self.bob).search([])
        self.assertFalse(rows)
        self.assertEqual(len(self.env["agile.recent.issue"].with_user(self.alice).search([])), 1)
