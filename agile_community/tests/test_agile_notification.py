from odoo import Command
from odoo.tests.common import TransactionCase, new_test_user


class TestAgileNotification(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, login="nt_manager", groups="project.group_project_manager")
        cls.alice = new_test_user(cls.env, login="nt_alice", groups="project.group_project_user")
        cls.bob = new_test_user(cls.env, login="nt_bob", groups="project.group_project_user")
        cls.project = cls.env["project.project"].with_user(cls.manager).create({
            "name": "Notify project", "privacy_visibility": "employees", "agile_enabled": True, "agile_key": "NTF",
        })
        for user in (cls.alice, cls.bob):
            member = cls.env["agile.project.member"].search([
                ("project_id", "=", cls.project.id), ("user_id", "=", user.id)])
            if member:
                member.with_user(cls.manager).role = "contributor"
            else:
                cls.env["agile.project.member"].with_user(cls.manager).create({
                    "project_id": cls.project.id, "user_id": user.id, "role": "contributor"})

    def _issue(self, creator=None, **vals):
        creator = creator or self.alice
        return self.env["project.task"].with_user(creator).create({
            "name": "Issue", "project_id": self.project.id, "description": "x", **vals})

    def _followers(self, issue):
        return issue.sudo().message_partner_ids

    def _recipients(self, issue, body="Hi", **post):
        """Partners a message to the issue would notify (computed without sending anything)."""
        message = issue.sudo().message_post(body=body, **post)
        recipients = issue._notify_get_recipients(message, {"partner_ids": message.partner_ids.ids,
                                                           "subtype_id": message.subtype_id.id,
                                                           "message_type": message.message_type})
        return {r["id"] for r in recipients}

    def test_watch_defaults_decide_who_follows_a_new_issue(self):
        issue = self._issue(user_ids=[Command.set([self.bob.id])])
        self.assertIn(self.alice.partner_id, self._followers(issue), "the creator follows by default")
        self.assertIn(self.bob.partner_id, self._followers(issue), "the assignee follows by default")
        self.project.write({"agile_watch_creator": False, "agile_watch_assignees": False})
        quiet = self._issue(user_ids=[Command.set([self.bob.id])])
        self.assertNotIn(self.alice.partner_id, self._followers(quiet))
        self.assertNotIn(self.bob.partner_id, self._followers(quiet))
        self.project.write({"agile_watch_managers": True})
        managed = self._issue()
        self.assertIn(self.manager.partner_id, self._followers(managed))

    def test_a_creator_who_is_also_assigned_keeps_following_when_only_creator_watch_is_off(self):
        self.project.write({"agile_watch_creator": False})
        issue = self._issue(user_ids=[Command.set([self.alice.id])])
        self.assertIn(self.alice.partner_id, self._followers(issue), "being assigned is a reason to follow")

    def test_status_and_comment_toggles_silence_followers_but_not_mentions(self):
        issue = self._issue(user_ids=[Command.set([self.bob.id])])
        comment = {"subtype_xmlid": "mail.mt_comment", "message_type": "comment"}
        self.assertIn(self.bob.partner_id.id, self._recipients(issue, **comment))
        self.project.write({"agile_notify_comments": False})
        self.assertNotIn(self.bob.partner_id.id, self._recipients(issue, **comment), "followers are not told")
        mentioned = self._recipients(issue, partner_ids=[self.bob.partner_id.id], **comment)
        self.assertIn(self.bob.partner_id.id, mentioned, "a mentioned person is always told")
        # Notes are not a switchable event.
        self.project.write({"agile_notify_comments": True, "agile_notify_status": False})
        stage = self.env.ref("project.mt_task_stage")
        self.assertNotIn(self.bob.partner_id.id, self._recipients(issue, subtype_xmlid="project.mt_task_stage"))
        self.assertEqual(stage.id, self.env.ref("project.mt_task_stage").id)
        self.assertIn(self.bob.partner_id.id, self._recipients(issue, **comment), "comments still go out")

    def test_a_person_is_told_once_per_message(self):
        issue = self._issue(user_ids=[Command.set([self.bob.id])])
        message = issue.sudo().message_post(body="Hi", subtype_xmlid="mail.mt_comment", message_type="comment",
                                            partner_ids=[self.bob.partner_id.id])
        recipients = issue._notify_get_recipients(message, {"partner_ids": [self.bob.partner_id.id]})
        ids = [r["id"] for r in recipients]
        self.assertEqual(len(ids), len(set(ids)), "no partner appears twice")

    def test_assignment_notice_follows_its_toggle(self):
        issue = self._issue()
        sent = []
        original = type(self.env["project.task"]).message_notify

        def counting(self_, *args, **kwargs):
            sent.append(kwargs.get("partner_ids"))
            return self.env["mail.message"]

        type(self.env["project.task"]).message_notify = counting
        try:
            issue.with_user(self.manager).write({"user_ids": [Command.set([self.bob.id])]})
            self.assertEqual(len(sent), 1, "assignment notice is on by default")
            self.project.write({"agile_notify_assignment": False})
            issue.with_user(self.manager).write({"user_ids": [Command.set([self.bob.id, self.alice.id])]})
            self.assertEqual(len(sent), 1, "switched off: nobody is told")
        finally:
            type(self.env["project.task"]).message_notify = original

    def test_native_projects_are_untouched(self):
        native = self.env["project.project"].with_user(self.manager).create({"name": "Plain"})
        task = self.env["project.task"].with_user(self.manager).create({"name": "T", "project_id": native.id})
        self.assertFalse(task._agile_notification_project())
        self.assertIn(self.manager.partner_id, task.sudo().message_partner_ids)
