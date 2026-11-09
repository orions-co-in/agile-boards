from odoo.tests.common import TransactionCase, new_test_user

MAIL = """From: {sender}
To: {to}
Subject: {subject}
Message-Id: <{mid}>
{extra}Content-Type: text/plain; charset=utf-8

{body}
"""


class TestAgileMail(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.domain = cls.env["mail.alias.domain"].search([], limit=1) or cls.env["mail.alias.domain"].create(
            {"name": "agile.example.com", "bounce_alias": "bounce", "catchall_alias": "catchall"}
        )
        cls.manager = new_test_user(cls.env, login="mail_manager", groups="project.group_project_manager", email="mm@example.com")
        cls.project = cls.env["project.project"].create({
            "name": "Mail project", "privacy_visibility": "employees", "user_id": cls.manager.id,
            "agile_enabled": True, "agile_key": "MAILQ", "alias_name": "mailq",
        })

    def _mail(self, sender="Ann <ann@customer.example>", subject="Checkout fails", mid="m1@customer.example", extra="", body="It breaks"):
        to = self.project.alias_email
        return MAIL.format(sender=sender, to=to, subject=subject, mid=mid, extra=extra, body=body)

    def _send(self, **kwargs):
        task_id = self.env["mail.thread"].message_process(False, self._mail(**kwargs))
        return self.env["project.task"].browse(task_id)

    def _tasks(self):
        return self.env["project.task"].search([("project_id", "=", self.project.id)])

    def test_mail_to_the_alias_creates_an_issue_with_a_key_and_the_reporter_follows(self):
        task = self._send(body="It breaks on step two")
        self.assertEqual((task.name, task.agile_issue, task.stage_id.name), ("Checkout fails", True, "Backlog"))
        self.assertTrue(task.issue_key.startswith("MAILQ-"))
        self.assertEqual(task.agile_task_type_id.name, "Task")
        self.assertIn("It breaks on step two", task.description)
        self.assertEqual(task.partner_id.email, "ann@customer.example")
        self.assertIn(task.partner_id, task.message_partner_ids)

    def test_a_reply_by_message_reference_threads_to_the_issue(self):
        task = self._send()
        before = len(self._tasks())
        self._send(subject="Re: anything", mid="m2@customer.example", extra="In-Reply-To: <m1@customer.example>\n", body="Second thought")
        self.assertEqual(len(self._tasks()), before)
        self.assertTrue(task.message_ids.filtered(lambda m: "Second thought" in (m.body or "")))

    def test_a_reply_naming_the_key_in_the_subject_threads_even_without_headers(self):
        task = self._send()
        before = len(self._tasks())
        self._send(subject=f"Re: [{task.issue_key}] checkout", mid="m3@customer.example", body="Still broken")
        self.assertEqual(len(self._tasks()), before)
        self.assertTrue(task.message_ids.filtered(lambda m: "Still broken" in (m.body or "")))
        short = "MAILQ-%d" % int(task.issue_key.split("-")[1])
        self._send(subject=f"{short.lower()} again", mid="m4@customer.example", body="Third note")
        self.assertEqual(len(self._tasks()), before)
        self.assertTrue(task.message_ids.filtered(lambda m: "Third note" in (m.body or "")))

    def test_a_stranger_naming_a_key_cannot_comment_on_the_issue(self):
        task = self._send()
        # A known contact (so the sender is recognised) who does not follow this issue.
        self.env["res.partner"].create({"name": "Eve", "email": "eve@elsewhere.example"})
        before = len(self._tasks())
        stranger = self._send(sender="Eve <eve@elsewhere.example>", subject=f"{task.issue_key} hello", mid="m5@elsewhere.example", body="Injected")
        self.assertNotEqual(stranger, task)
        self.assertEqual(len(self._tasks()), before + 1)
        self.assertFalse(task.message_ids.filtered(lambda m: "Injected" in (m.body or "")))

    def test_a_key_from_another_project_is_not_followed(self):
        other = self.env["project.project"].create({
            "name": "Other", "privacy_visibility": "employees", "user_id": self.manager.id,
            "agile_enabled": True, "agile_key": "OTHM",
        })
        foreign = self.env["project.task"].create({"name": "Foreign", "project_id": other.id})
        foreign.message_subscribe(partner_ids=self._send().partner_id.ids)
        created = self._send(subject=f"{foreign.issue_key} please", mid="m6@customer.example")
        self.assertEqual(created.project_id, self.project)
        self.assertNotEqual(created, foreign)

    def test_who_can_email_is_respected(self):
        self.project.alias_contact = "followers"
        before = len(self._tasks())
        self.env["mail.thread"].message_process(False, self._mail(mid="m7@customer.example"))
        self.assertEqual(len(self._tasks()), before, "an unknown sender is refused when only followers may email")
