from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user


class TestAgileIssueTemplate(TransactionCase):
    def setUp(self):
        super().setUp()
        self.project = self.env["project.project"].create({
            "name": "Template project",
            "agile_enabled": True,
            "agile_key": "TMPL",
        })

    def test_save_and_create_from_template_preserves_identity_and_resets_checklist(self):
        issue = self.env["project.task"].create({
            "name": "Deployment request",
            "project_id": self.project.id,
            "agile_acceptance_criteria": "<p>Health check succeeds.</p>",
            "agile_checklist_item_ids": [Command.create({
                "name": "Verify rollback path",
                "is_done": True,
            })],
        })
        original_key = issue.issue_key

        action = issue.action_convert_to_template()
        template = self.env["project.task"].browse(action["res_id"])
        self.assertTrue(issue.agile_issue)
        self.assertEqual(issue.issue_key, original_key)
        self.assertTrue(template.is_template)
        self.assertFalse(template.agile_issue)
        self.assertFalse(template.issue_key)
        self.assertFalse(template.child_ids)
        self.assertEqual(template.agile_acceptance_criteria, issue.agile_acceptance_criteria)
        self.assertEqual(template.agile_checklist_item_ids.mapped("name"), ["Verify rollback path"])

        new_issue = self.env["project.task"].browse(template.action_create_from_template())
        self.assertTrue(new_issue.agile_issue)
        self.assertFalse(new_issue.is_template)
        self.assertEqual(new_issue.project_id, self.project)
        self.assertEqual(new_issue.agile_task_type_id, template.agile_task_type_id)
        self.assertNotEqual(new_issue.issue_key, original_key)
        self.assertEqual(new_issue.agile_acceptance_criteria, template.agile_acceptance_criteria)
        self.assertNotEqual(
            new_issue.agile_checklist_item_ids,
            template.agile_checklist_item_ids,
        )
        self.assertFalse(new_issue.agile_checklist_item_ids.is_done)

    def test_template_identity_cannot_be_changed_into_or_out_of_a_live_issue(self):
        issue = self.env["project.task"].create({
            "name": "Immutable issue identity", "project_id": self.project.id,
        })
        with self.assertRaisesRegex(ValidationError, "separate template"):
            issue.write({"is_template": True})
        template = issue.with_context(convert_to_template=True).copy({
            "is_template": True,
            "agile_issue": False,
            "issue_key": False,
        })
        with self.assertRaisesRegex(ValidationError, "Create from Template"):
            template.write({"is_template": False})

    def test_recurrence_copies_agile_scope_and_restarts_in_backlog(self):
        issue = self.env["project.task"].create({
            "name": "Recurring intake", "project_id": self.project.id,
        })
        recurrence = self.env["project.task.recurrence"].create({})
        values = self.env["project.task.recurrence"]._create_next_occurrences_values({
            issue: recurrence,
        })[0]
        backlog = self.project.type_ids.filtered(lambda stage: stage.agile_status == "backlog")[:1]
        self.assertEqual(values["project_id"], self.project.id)
        self.assertEqual(values["agile_task_type_id"], issue.agile_task_type_id.id)
        self.assertEqual(values["stage_id"], backlog.id)
        self.assertFalse(values["issue_key"])
        self.assertFalse(values["sprint_id"])

    def test_stakeholder_cannot_change_recurrence_settings(self):
        issue = self.env["project.task"].create({
            "name": "Stakeholder recurrence", "project_id": self.project.id,
        })
        stakeholder = new_test_user(
            self.env,
            login="template_stakeholder",
            groups="project.group_project_user",
        )
        self.env["agile.project.member"].create({
            "project_id": self.project.id,
            "user_id": stakeholder.id,
            "role": "stakeholder",
        })
        with self.assertRaises(AccessError):
            issue.with_user(stakeholder).write({"recurring_task": True})

    def test_stale_project_member_cannot_read_or_change_assigned_issue_checklist(self):
        self.project.write({"privacy_visibility": "employees"})
        contributor = new_test_user(
            self.env,
            login="checklist_contributor_revoked",
            groups="project.group_project_user",
        )
        self.env["agile.project.member"].create({
            "project_id": self.project.id,
            "user_id": contributor.id,
            "role": "contributor",
        })
        issue = self.env["project.task"].create({
            "name": "Assigned checklist issue",
            "project_id": self.project.id,
            "user_ids": [Command.set([contributor.id])],
        })
        item = self.env["agile.issue.checklist.item"].create({
            "task_id": issue.id,
            "name": "Private acceptance step",
        })

        self.project.write({"privacy_visibility": "followers"})

        self.assertTrue(issue.with_user(contributor).has_access("read"))
        self.assertFalse(self.project.with_user(contributor).has_access("read"))
        self.assertFalse(self.env["agile.issue.checklist.item"].with_user(
            contributor
        ).search([("id", "=", item.id)]))
        with self.assertRaises(AccessError):
            item.with_user(contributor).write({"is_done": True})
        with self.assertRaises(AccessError):
            self.env["agile.issue.checklist.item"].with_user(contributor).create({
                "task_id": issue.id,
                "name": "Unauthorized checklist step",
            })
        with self.assertRaises(AccessError):
            item.with_user(contributor).unlink()

    def test_stale_project_manager_cannot_edit_template_or_recurrence(self):
        self.project.write({"privacy_visibility": "employees"})
        contributor = new_test_user(
            self.env,
            login="template_manager_revoked",
            groups="project.group_project_user",
        )
        self.env["agile.project.member"].create({
            "project_id": self.project.id,
            "user_id": contributor.id,
            "role": "manager",
        })
        issue = self.env["project.task"].create({
            "name": "Recurring issue for template audit",
            "project_id": self.project.id,
            "user_ids": [Command.set([contributor.id])],
        })
        issue.write({"recurring_task": True, "repeat_interval": 1})
        template_action = issue.action_convert_to_template()
        template = self.env["project.task"].browse(template_action["res_id"])
        template.write({"user_ids": [Command.set([contributor.id])]})

        self.project.write({"privacy_visibility": "followers"})

        self.assertTrue(issue.with_user(contributor).has_access("read"))
        self.assertTrue(template.with_user(contributor).has_access("read"))
        self.assertFalse(self.project.with_user(contributor).has_access("read"))
        recurrence = issue.recurrence_id
        with self.assertRaises(AccessError):
            recurrence.with_user(contributor).write({"repeat_interval": 2})
        with self.assertRaises(AccessError):
            recurrence.with_user(contributor).unlink()
        with self.assertRaises(AccessError):
            template.with_user(contributor).write({
                "agile_acceptance_criteria": "Unauthorized template edit",
            })
        with self.assertRaises(AccessError):
            template.with_user(contributor).action_create_from_template()

    def test_contributor_can_instantiate_but_not_configure_a_template(self):
        issue = self.env["project.task"].create({
            "name": "Template source", "project_id": self.project.id,
        })
        action = issue.action_convert_to_template()
        template = self.env["project.task"].browse(action["res_id"])
        contributor = new_test_user(
            self.env,
            login="template_contributor",
            groups="project.group_project_user",
        )
        self.env["agile.project.member"].create({
            "project_id": self.project.id,
            "user_id": contributor.id,
            "role": "contributor",
        })
        with self.assertRaises(AccessError):
            template.with_user(contributor).write({
                "agile_acceptance_criteria": "Unauthorized template edit",
            })
        new_issue = self.env["project.task"].browse(
            template.with_user(contributor).action_create_from_template()
        )
        self.assertTrue(new_issue.agile_issue)
        self.assertEqual(new_issue.project_id, self.project)

    def test_template_instantiation_requires_an_active_backlog_stage(self):
        issue = self.env["project.task"].create({
            "name": "Backlog stage required", "project_id": self.project.id,
        })
        action = issue.action_convert_to_template()
        template = self.env["project.task"].browse(action["res_id"])
        backlog = self.project.type_ids.filtered(
            lambda stage: stage.agile_status == "backlog"
        )[:1]
        backlog.active = False

        with self.assertRaisesRegex(ValidationError, "Restore.*Backlog"):
            template.action_create_from_template()
