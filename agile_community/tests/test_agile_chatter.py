from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, new_test_user


class TestAgileChatter(TransactionCase):
    def setUp(self):
        super().setUp()
        self.project = self.env["project.project"].create({
            "name": "Chatter role project",
            "agile_enabled": True,
            "agile_key": "CHAT",
        })
        self.issue = self.env["project.task"].create({
            "name": "Private discussion",
            "project_id": self.project.id,
        })
        self.stakeholder = new_test_user(
            self.env,
            login="agile_chatter_stakeholder",
            groups="project.group_project_user",
        )
        self.reviewer = new_test_user(
            self.env,
            login="agile_chatter_reviewer",
            groups="project.group_project_user",
        )
        self.env["agile.project.member"].create([
            {
                "project_id": self.project.id,
                "user_id": self.stakeholder.id,
                "role": "stakeholder",
            },
            {
                "project_id": self.project.id,
                "user_id": self.reviewer.id,
                "role": "reviewer",
            },
        ])

    def test_stakeholder_cannot_post_through_chatter_or_message_create(self):
        with self.assertRaisesRegex(AccessError, "Only Agile managers"):
            self.issue.with_user(self.stakeholder).message_post(
                body="Stakeholders are read-only."
            )
        with self.assertRaisesRegex(AccessError, "Only Agile managers"):
            self.env["mail.message"].with_user(self.stakeholder).create({
                "model": "project.task",
                "res_id": self.issue.id,
                "body": "Direct message create must also be denied.",
            })

    def test_stakeholder_can_manage_self_follow_but_not_other_followers(self):
        self.issue.with_user(self.stakeholder).message_subscribe(
            partner_ids=[self.stakeholder.partner_id.id]
        )
        self.issue.with_user(self.stakeholder).message_unsubscribe(
            partner_ids=[self.stakeholder.partner_id.id]
        )
        other_partner = self.env["res.partner"].create({
            "name": "Another Agile project watcher",
        })

        with self.assertRaisesRegex(AccessError, "change other followers"):
            self.env["mail.followers"].with_user(self.stakeholder).create({
                "res_model": "project.task",
                "res_id": self.issue.id,
                "partner_id": other_partner.id,
            })

    def test_stakeholder_cannot_reply_to_agile_message_by_parent_id_only(self):
        parent = self.env["mail.message"].sudo().create({
            "model": "project.task",
            "res_id": self.issue.id,
            "partner_ids": [Command.link(self.stakeholder.partner_id.id)],
            "body": "Issue discussion parent.",
        })
        with self.assertRaisesRegex(AccessError, "Only Agile managers"):
            self.env["mail.message"].with_user(self.stakeholder).create({
                "parent_id": parent.id,
                "body": "This reply omits model and res_id.",
            })

    def test_cannot_retarget_existing_message_to_agile_issue_without_role(self):
        message = self.env["mail.message"].sudo().create({
            "body": "Previously unlinked message.",
        })
        with self.assertRaisesRegex(AccessError, "Only Agile managers"):
            message.with_user(self.stakeholder).write({
                "model": "project.task",
                "res_id": self.issue.id,
            })

    def test_reviewer_can_post_to_agile_issue_chatter(self):
        message = self.issue.with_user(self.reviewer).message_post(
            body="Review feedback."
        )
        self.assertEqual(message.model, "project.task")
        self.assertEqual(message.res_id, self.issue.id)

    def test_retained_reviewer_role_cannot_read_chatter_after_project_access_revoked(
        self,
    ):
        self.project.write({"privacy_visibility": "followers"})
        self.project.message_subscribe(
            partner_ids=[self.reviewer.partner_id.id]
        )
        self.issue.write({"user_ids": [Command.link(self.reviewer.id)]})
        message = self.issue.message_post(body="Private review history.")
        self.project.message_unsubscribe(
            partner_ids=[self.reviewer.partner_id.id]
        )

        self.assertTrue(self.issue.with_user(self.reviewer).has_access("read"))
        self.assertFalse(self.project.with_user(self.reviewer).has_access("read"))
        self.assertFalse(message.with_user(self.reviewer).has_access("read"))

    def test_retained_reviewer_role_cannot_read_activity_after_project_access_revoked(
        self,
    ):
        self.project.write({"privacy_visibility": "followers"})
        self.project.message_subscribe(
            partner_ids=[self.reviewer.partner_id.id]
        )
        self.issue.write({"user_ids": [Command.link(self.reviewer.id)]})
        activity = self.issue.activity_schedule(
            "mail.mail_activity_data_todo",
            user_id=self.reviewer.id,
            summary="Private review follow-up",
        )
        self.project.message_unsubscribe(
            partner_ids=[self.reviewer.partner_id.id]
        )

        self.assertTrue(self.issue.with_user(self.reviewer).has_access("read"))
        self.assertFalse(self.project.with_user(self.reviewer).has_access("read"))
        self.assertFalse(activity.with_user(self.reviewer).has_access("read"))

    def test_stakeholder_cannot_edit_own_or_delete_issue_chatter(self):
        message = self.env["mail.message"].sudo().create({
            "model": "project.task",
            "res_id": self.issue.id,
            "author_id": self.stakeholder.partner_id.id,
            "body": "Historical stakeholder message.",
        })
        with self.assertRaisesRegex(AccessError, "Only Agile managers"):
            message.with_user(self.stakeholder).write({
                "body": "Edited through the message model."
            })
        with self.assertRaisesRegex(AccessError, "Only Agile managers"):
            message.with_user(self.stakeholder).unlink()

    def test_non_agile_project_chatter_keeps_native_mutation_behavior(self):
        native_project = self.env["project.project"].create({
            "name": "Native chatter project",
        })
        native_task = self.env["project.task"].create({
            "name": "Native chatter task",
            "project_id": native_project.id,
        })
        message = native_task.with_user(self.reviewer).message_post(
            body="Ordinary Project comment."
        )
        message.with_user(self.reviewer).write({
            "body": "Updated ordinary Project comment."
        })
        self.assertIn("Updated ordinary Project comment", message.body)

    def test_stakeholder_cannot_manage_issue_activities_or_other_followers(self):
        self.issue.with_user(self.stakeholder).message_subscribe(
            partner_ids=[self.stakeholder.partner_id.id]
        )
        with self.assertRaisesRegex(AccessError, "cannot change its issues"):
            self.issue.with_user(self.stakeholder).message_subscribe(
                partner_ids=[self.reviewer.partner_id.id]
            )
        with self.assertRaisesRegex(AccessError, "cannot change its issues"):
            self.issue.with_user(self.stakeholder).message_unsubscribe(
                partner_ids=[self.reviewer.partner_id.id]
            )
        self.issue.with_user(self.stakeholder).message_unsubscribe(
            partner_ids=[self.stakeholder.partner_id.id]
        )

        activity_values = {
            "res_model_id": self.env["ir.model"]._get("project.task").id,
            "res_id": self.issue.id,
            "user_id": self.reviewer.id,
            "summary": "Review the issue",
        }
        with self.assertRaisesRegex(AccessError, "Only Agile managers"):
            self.env["mail.activity"].with_user(self.stakeholder).create(
                activity_values
            )

        activity = self.env["mail.activity"].sudo().create(activity_values)
        with self.assertRaisesRegex(AccessError, "Only Agile managers"):
            activity.with_user(self.stakeholder).write({"summary": "Changed"})
        with self.assertRaisesRegex(AccessError, "Only Agile managers"):
            activity.with_user(self.stakeholder).unlink()

    def test_reviewer_can_manage_issue_activity_and_native_activity_is_unchanged(self):
        activity_values = {
            "res_model_id": self.env["ir.model"]._get("project.task").id,
            "res_id": self.issue.id,
            "user_id": self.reviewer.id,
            "summary": "Review the issue",
        }
        activity = self.env["mail.activity"].with_user(self.reviewer).create(
            activity_values
        )
        activity.write({"summary": "Review the updated issue"})
        self.assertEqual(activity.summary, "Review the updated issue")

        native_project = self.env["project.project"].create({
            "name": "Native activity project",
        })
        native_task = self.env["project.task"].create({
            "name": "Native activity task",
            "project_id": native_project.id,
        })
        native_activity = self.env["mail.activity"].with_user(self.reviewer).create({
            **activity_values,
            "res_id": native_task.id,
            "user_id": self.reviewer.id,
        })
        native_activity.write({"summary": "Updated native follow-up"})
        self.assertEqual(native_activity.summary, "Updated native follow-up")

    def test_removed_member_cannot_read_issue_message_activity_or_follower(self):
        parent = self.env["mail.message"].sudo().create({
            "model": "project.task",
            "res_id": self.issue.id,
            "body": "The root message for a nested reply.",
        })
        message = self.env["mail.message"].sudo().create({
            "model": "project.task",
            "res_id": self.issue.id,
            "author_id": self.stakeholder.partner_id.id,
            "partner_ids": [Command.link(self.stakeholder.partner_id.id)],
            "body": "A notification must not preserve access after removal.",
        })
        reply = self.env["mail.message"].sudo().create({
            "parent_id": parent.id,
            "author_id": self.stakeholder.partner_id.id,
            "body": "A nested reply with no direct document link.",
        })
        activity = self.env["mail.activity"].sudo().create({
            "res_model_id": self.env["ir.model"]._get("project.task").id,
            "res_id": self.issue.id,
            "user_id": self.stakeholder.id,
            "summary": "Private follow-up",
        })
        follower = self.env["mail.followers"].sudo().search([
            ("res_model", "=", "project.task"),
            ("res_id", "=", self.issue.id),
            ("partner_id", "=", self.stakeholder.partner_id.id),
        ], limit=1)
        if not follower:
            follower = self.env["mail.followers"].sudo().create({
                "res_model": "project.task",
                "res_id": self.issue.id,
                "partner_id": self.stakeholder.partner_id.id,
            })
        self.env["agile.project.member"].sudo().search([
            ("project_id", "=", self.project.id),
            ("user_id", "=", self.stakeholder.id),
        ]).unlink()

        self.assertNotIn(
            message.id,
            self.env["mail.message"].with_user(self.stakeholder).search([
                ("id", "=", message.id),
            ]).ids,
        )
        self.assertNotIn(
            reply.id,
            self.env["mail.message"].with_user(self.stakeholder).search([
                ("id", "=", reply.id),
            ]).ids,
        )
        self.assertNotIn(
            activity.id,
            self.env["mail.activity"].with_user(self.stakeholder).search([
                ("id", "=", activity.id),
            ]).ids,
        )
        self.assertNotIn(
            follower.id,
            self.env["mail.followers"].with_user(self.stakeholder).search([
                ("id", "=", follower.id),
            ]).ids,
        )

    def test_stakeholder_cannot_create_edit_or_delete_issue_attachments(self):
        attachment_model = self.env["ir.attachment"]
        values = {
            "name": "issue-note.txt",
            "res_model": "project.task",
            "res_id": self.issue.id,
        }
        with self.assertRaisesRegex(AccessError, "Only Agile managers"):
            attachment_model.with_user(self.stakeholder).create(values)

        attachment = attachment_model.sudo().create(values)
        with self.assertRaisesRegex(AccessError, "Only Agile managers"):
            attachment.with_user(self.stakeholder).write({"name": "renamed.txt"})
        with self.assertRaisesRegex(AccessError, "Only Agile managers"):
            attachment.with_user(self.stakeholder).unlink()

    def test_checklist_records_do_not_escape_agile_team_through_global_groups(self):
        project_manager = new_test_user(
            self.env,
            login="agile_chatter_unassigned_manager",
            groups="project.group_project_manager",
        )
        system_admin = new_test_user(
            self.env,
            login="agile_chatter_system_admin",
            groups="base.group_system",
        )
        item = self.env["agile.issue.checklist.item"].sudo().create({
            "task_id": self.issue.id,
            "name": "Private acceptance item",
        })
        self.project.write({"privacy_visibility": "followers"})

        self.assertTrue(self.project.with_user(project_manager).has_access("read"))
        self.assertFalse(self.project.with_user(system_admin).has_access("read"))
        self.assertFalse(
            self.env["agile.issue.checklist.item"].with_user(
                project_manager
            ).search([("id", "=", item.id)])
        )
        self.assertFalse(
            self.env["agile.issue.checklist.item"].with_user(
                system_admin
            ).search([("id", "=", item.id)])
        )

    def test_reviewer_can_mutate_issue_attachments(self):
        attachment = self.env["ir.attachment"].with_user(self.reviewer).create({
            "name": "review-note.txt",
            "res_model": "project.task",
            "res_id": self.issue.id,
        })
        attachment.write({"name": "review-note-updated.txt"})
        self.assertEqual(attachment.name, "review-note-updated.txt")

    def test_attachment_read_requires_current_project_access(self):
        attachment = self.env["ir.attachment"].sudo().create({
            "name": "private-issue-file.txt",
            "res_model": "project.task",
            "res_id": self.issue.id,
        })
        self.project.write({"privacy_visibility": "followers"})
        self.project.message_subscribe(
            partner_ids=[self.reviewer.partner_id.id]
        )
        self.issue.write({"user_ids": [Command.link(self.reviewer.id)]})
        self.project.message_unsubscribe(
            partner_ids=[self.reviewer.partner_id.id]
        )

        self.assertTrue(self.issue.with_user(self.reviewer).has_access("read"))
        self.assertFalse(self.project.with_user(self.reviewer).has_access("read"))
        self.assertFalse(attachment.with_user(self.reviewer).has_access("read"))

    def test_retained_reviewer_role_cannot_mutate_attachment_after_access_revoked(
        self,
    ):
        self.project.write({"privacy_visibility": "followers"})
        self.project.message_subscribe(
            partner_ids=[self.reviewer.partner_id.id]
        )
        self.issue.write({"user_ids": [Command.link(self.reviewer.id)]})
        self.project.message_unsubscribe(
            partner_ids=[self.reviewer.partner_id.id]
        )

        self.assertTrue(self.issue.with_user(self.reviewer).has_access("read"))
        self.assertFalse(self.project.with_user(self.reviewer).has_access("read"))
        with self.assertRaisesRegex(AccessError, "native Odoo Project access"):
            self.env["ir.attachment"].with_user(self.reviewer).create({
                "name": "denied-note.txt",
                "res_model": "project.task",
                "res_id": self.issue.id,
            })

    def test_non_agile_project_attachment_keeps_native_mutation_behavior(self):
        native_project = self.env["project.project"].create({
            "name": "Native attachment project",
        })
        native_task = self.env["project.task"].create({
            "name": "Native attachment task",
            "project_id": native_project.id,
        })
        attachment = self.env["ir.attachment"].with_user(self.reviewer).create({
            "name": "native-note.txt",
            "res_model": "project.task",
            "res_id": native_task.id,
        })
        attachment.write({"name": "native-note-updated.txt"})
        self.assertEqual(attachment.name, "native-note-updated.txt")

    def test_stakeholder_gets_no_flag_button_and_a_truthful_message(self):
        # NU-09: the Flag button was offered, then refused as if the person were not a member.
        stakeholder_issue = self.issue.with_user(self.stakeholder)
        self.assertFalse(stakeholder_issue.can_agile_flag)
        self.assertTrue(self.issue.with_user(self.reviewer).can_agile_flag)
        with self.assertRaisesRegex(AccessError, "Stakeholders can follow this project"):
            stakeholder_issue.action_agile_toggle_flag()
