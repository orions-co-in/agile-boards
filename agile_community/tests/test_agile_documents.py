from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user


class TestAgileDocuments(TransactionCase):
    """S-1131: titled links to web pages and Odoo pages on an issue."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, login="doc_manager", groups="project.group_project_manager")
        cls.project = cls.env["project.project"].with_user(cls.manager).create(
            {"name": "Docs", "agile_enabled": True, "agile_key": "DOC", "agile_method": "kanban"}
        )
        cls.viewer = new_test_user(cls.env, login="doc_viewer", groups="project.group_project_user")
        cls.env["agile.project.member"].sudo().create(
            {"project_id": cls.project.id, "user_id": cls.viewer.id, "role": "stakeholder"}
        )
        cls.issue = cls.env["project.task"].with_user(cls.manager).create({"name": "Spec", "project_id": cls.project.id})

    def _add(self, **values):
        return self.env["agile.issue.document"].with_user(self.manager).create(
            {"task_id": self.issue.id, "title": "Design doc", "url": "https://example.com/doc", **values}
        )

    def test_a_web_page_and_an_odoo_page_get_their_type(self):
        web = self._add()
        article = self._add(title="Runbook", url="/odoo/knowledge/3")
        self.assertEqual((web.kind, article.kind), ("web", "odoo"))
        self.assertEqual(self.issue.agile_document_count, 2)

    def test_unsafe_or_malformed_links_are_refused(self):
        for url in ("javascript:alert(1)", "example.com/doc", "https://exa mple.com", "//evil.test/x", "https://" + "a" * 2000):
            with self.assertRaises(ValidationError, msg=url), self.cr.savepoint():
                self._add(url=url)

    def test_a_title_is_needed(self):
        with self.assertRaises(ValidationError):
            self._add(title="   ")

    def test_a_stakeholder_reads_but_cannot_change_links(self):
        document = self._add()
        self.assertEqual(document.with_user(self.viewer).title, "Design doc")
        with self.assertRaises(AccessError):
            document.with_user(self.viewer).write({"title": "Mine"})
        with self.assertRaises(AccessError):
            self.env["agile.issue.document"].with_user(self.viewer).create(
                {"task_id": self.issue.id, "title": "X", "url": "https://example.com"}
            )

    def test_links_follow_the_issue_when_it_is_cloned(self):
        self._add()
        clone = self.issue.copy()
        self.assertEqual(clone.agile_document_ids.mapped("title"), ["Design doc"])

    def test_an_issue_holds_at_most_fifty_links(self):
        for number in range(50):
            self._add(title="D%s" % number)
        with self.assertRaises(ValidationError):
            self._add(title="One too many")

    def test_links_on_a_restricted_issue_are_hidden_from_other_people(self):
        document = self._add()
        self.issue.write({"agile_restricted": True})
        self.assertFalse(self.env["agile.issue.document"].with_user(self.viewer).search([("id", "=", document.id)]))
