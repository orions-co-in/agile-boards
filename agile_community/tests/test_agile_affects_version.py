from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, new_test_user


class TestAgileAffectsVersion(TransactionCase):
    """S-1121: a bug can name the releases it was found in."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, login="av_manager", groups="project.group_project_manager")
        Project = cls.env["project.project"].with_user(cls.manager)
        cls.project = Project.create({"name": "Affects", "agile_enabled": True, "agile_key": "AFV", "agile_method": "kanban"})
        cls.other = Project.create({"name": "Other", "agile_enabled": True, "agile_key": "AFO", "agile_method": "kanban"})
        Version = cls.env["project.version"].with_user(cls.manager)
        cls.v1 = Version.create({"name": "1.0", "project_id": cls.project.id})
        cls.v2 = Version.create({"name": "2.0", "project_id": cls.project.id})
        cls.foreign = Version.create({"name": "9.0", "project_id": cls.other.id})
        cls.Task = cls.env["project.task"].with_user(cls.manager)

    def _bug(self, name="Bug", **extra):
        return self.Task.create({"name": name, "project_id": self.project.id, **extra})

    def test_an_issue_can_name_several_releases_it_was_found_in(self):
        bug = self._bug(agile_affects_version_ids=[(6, 0, (self.v1 | self.v2).ids)])
        self.assertEqual(bug.agile_affects_version_ids, self.v1 | self.v2)

    def test_the_fix_version_is_a_separate_field(self):
        bug = self._bug(version_id=self.v2.id, agile_affects_version_ids=[(6, 0, self.v1.ids)])
        self.assertEqual((bug.version_id, bug.agile_affects_version_ids), (self.v2, self.v1))

    def test_a_release_of_another_project_is_refused(self):
        with self.assertRaises(ValidationError):
            self._bug(agile_affects_version_ids=[(6, 0, self.foreign.ids)])
        bug = self._bug()
        with self.assertRaises(ValidationError):
            bug.write({"agile_affects_version_ids": [(4, self.foreign.id)]})

    def test_the_release_counts_the_issues_found_in_it_and_opens_them(self):
        first = self._bug("First", agile_affects_version_ids=[(6, 0, self.v1.ids)])
        self._bug("Second", agile_affects_version_ids=[(6, 0, (self.v1 | self.v2).ids)])
        self.assertEqual((self.v1.affected_issue_count, self.v2.affected_issue_count), (2, 1))
        action = self.v1.with_user(self.manager).action_view_affected_issues()
        found = self.env["project.task"].search(action["domain"])
        self.assertIn(first, found)
        self.assertEqual(len(found), 2)

    def test_the_query_language_searches_by_affects_version(self):
        from odoo.addons.agile_community.models.agile_query import AgileQuery

        hit = self._bug("Hit", agile_affects_version_ids=[(6, 0, self.v1.ids)])
        self._bug("Miss", agile_affects_version_ids=[(6, 0, self.v2.ids)])
        query = AgileQuery(self.env(user=self.manager), self.project)
        domain, _words = query.compile('affectsVersion = "1.0"')
        self.assertEqual(self.env["project.task"].search(domain), hit)
        domain, _words = query.compile("affectsVersion IS EMPTY")
        self.assertNotIn(hit, self.env["project.task"].search(domain))

    def test_the_search_view_offers_the_field(self):
        view = self.env.ref("agile_community.project_task_search_agile")
        self.assertIn("agile_affects_version_ids", view.arch)
