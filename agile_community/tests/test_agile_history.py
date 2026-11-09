from markupsafe import Markup

from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, new_test_user


class TestAgileHistoryFeed(TransactionCase):
    """S-1128: one feed that the History panel splits into Comments, History and Work log."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, login="hist_manager", groups="project.group_project_manager")
        cls.project = cls.env["project.project"].with_user(cls.manager).create(
            {"name": "History", "agile_enabled": True, "agile_key": "HST", "agile_method": "kanban"}
        )
        cls.outsider = new_test_user(cls.env, login="hist_outsider", groups="project.group_project_user")
        cls.issue = cls.env["project.task"].with_user(cls.manager).create({"name": "Tracked", "project_id": cls.project.id})

    def _feed(self, user=None):
        return self.issue.with_user(user or self.manager).agile_history_feed()

    def test_a_comment_is_listed_as_a_comment(self):
        self.issue.with_user(self.manager).message_post(body=Markup("<p>Looks good</p>"), message_type="comment", subtype_xmlid="mail.mt_comment")
        comments = [e for e in self._feed()["entries"] if e["kind"] == "comment"]
        self.assertEqual([c["text"] for c in comments], ["Looks good"])
        self.assertFalse(comments[0]["note"])

    def test_an_internal_note_is_marked_as_a_note(self):
        self.issue.with_user(self.manager).message_post(body="Careful", message_type="comment", subtype_xmlid="mail.mt_note")
        comment = next(e for e in self._feed()["entries"] if e["kind"] == "comment")
        self.assertTrue(comment["note"])

    def test_a_tracked_change_is_listed_as_history_with_old_and_new(self):
        ready = self.project.type_ids.filtered(lambda stage: stage.agile_status == "ready")[:1]
        self.issue.with_user(self.manager).write({"stage_id": ready.id})
        changes = [c for e in self._feed()["entries"] if e["kind"] == "history" for c in e["changes"]]
        self.assertTrue(any(c["field"] and c["new"] == ready.name for c in changes), changes)

    def test_newest_entries_come_first(self):
        post = self.issue.with_user(self.manager).message_post
        post(body="first", message_type="comment", subtype_xmlid="mail.mt_comment")
        post(body="second", message_type="comment", subtype_xmlid="mail.mt_comment")
        texts = [e["text"] for e in self._feed()["entries"] if e["kind"] == "comment"]
        self.assertEqual(texts, ["second", "first"])

    def test_work_log_is_unavailable_without_the_timesheets_app(self):
        feed = self._feed()
        if "timesheet_ids" not in self.env["project.task"]._fields:
            self.assertFalse(feed["worklog_available"])
            self.assertFalse([e for e in feed["entries"] if e["kind"] == "worklog"])

    def test_a_person_outside_the_team_cannot_read_the_feed(self):
        self.issue.with_user(self.manager).message_post(body="Private", message_type="comment", subtype_xmlid="mail.mt_comment")
        with self.assertRaises(AccessError):
            self._feed(self.outsider)
