from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user


class TestAgileWorkflow(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(
            cls.env,
            login="workflow_manager",
            groups="project.group_project_manager",
        )
        cls.contributor = new_test_user(
            cls.env,
            login="workflow_contributor",
            groups="project.group_project_user",
        )
        cls.reviewer = new_test_user(
            cls.env,
            login="workflow_reviewer",
            groups="agile_community.group_agile_reviewer",
        )
        cls.stakeholder = new_test_user(
            cls.env,
            login="workflow_stakeholder",
            groups="agile_community.group_agile_stakeholder",
        )
        cls.project = cls.env["project.project"].create({
            "name": "Workflow",
            "privacy_visibility": "employees",
            "user_id": cls.manager.id,
            "agile_enabled": True,
            "agile_key": "FLOW",
            "agile_method": "kanban",
        })
        cls.stages = {
            stage.agile_status: stage
            for stage in cls.project.type_ids.filtered("agile_status")
        }

    def _new_issue(self, name="Workflow issue"):
        return self.env["project.task"].create({
            "name": name,
            "project_id": self.project.id,
            "description": "A testable description.",
        })

    def test_default_stages_and_native_state_mapping(self):
        self.assertEqual(
            set(self.stages),
            {"backlog", "ready", "progress", "review", "done", "canceled"},
        )
        self.assertEqual(self.stages["canceled"].fold, True)
        task = self._new_issue()
        self.assertEqual(task.agile_status, "backlog")
        self.assertEqual(task.state, "01_in_progress")

        task.with_user(self.manager).action_agile_cancel()
        self.assertEqual(task.state, "1_canceled")
        task.with_user(self.manager).action_agile_reopen()
        self.assertEqual(task.agile_status, "backlog")
        self.assertEqual(task.state, "01_in_progress")

    def test_contributor_follows_forward_workflow(self):
        task = self._new_issue()
        contributor_task = task.with_user(self.contributor)
        contributor_task.action_agile_mark_ready()
        self.assertEqual(task.agile_status, "ready")
        contributor_task.action_agile_start()
        self.assertEqual(task.agile_status, "progress")
        contributor_task.action_agile_send_review()
        self.assertEqual(task.agile_status, "review")
        with self.assertRaises(UserError):
            contributor_task.action_agile_complete()

    def test_reviewer_can_return_or_complete_review(self):
        task = self._new_issue()
        task.with_user(self.manager).write({"stage_id": self.stages["ready"].id})
        task.with_user(self.manager).write({"stage_id": self.stages["progress"].id})
        task.with_user(self.manager).write({"stage_id": self.stages["review"].id})

        reviewer_task = task.with_user(self.reviewer)
        reviewer_task.action_agile_return()
        self.assertEqual(task.agile_status, "progress")
        task.with_user(self.manager).action_agile_send_review()
        reviewer_task.action_agile_complete()
        self.assertEqual(task.agile_status, "done")
        self.assertEqual(task.state, "1_done")

    def test_manager_can_reopen_and_cancel_but_not_skip(self):
        task = self._new_issue()
        manager_task = task.with_user(self.manager)
        with self.assertRaises(UserError):
            manager_task.write({"stage_id": self.stages["done"].id})
        manager_task.action_agile_cancel()
        self.assertEqual(task.agile_status, "canceled")
        manager_task.action_agile_reopen()
        self.assertEqual(task.agile_status, "backlog")

    def test_canceled_stage_requires_detail_action(self):
        task = self._new_issue()
        with self.assertRaisesRegex(UserError, "detail page"):
            task.with_user(self.manager).write({
                "stage_id": self.stages["canceled"].id,
            })
        task.with_user(self.manager).action_agile_cancel()
        self.assertEqual(task.agile_status, "canceled")

    def test_board_rpc_and_direct_state_share_server_rules(self):
        task = self._new_issue()
        contributor_task = task.with_user(self.contributor)
        with self.assertRaises(UserError):
            contributor_task.write({"stage_id": self.stages["review"].id})
        with self.assertRaises(UserError):
            contributor_task.write({"state": "1_done"})
        self.assertEqual(task.agile_status, "backlog")
        self.assertEqual(task.state, "01_in_progress")

    def test_stakeholder_is_read_only(self):
        task = self._new_issue()
        stakeholder_task = task.with_user(self.stakeholder)
        self.assertEqual(stakeholder_task.name, task.name)
        with self.assertRaises(AccessError):
            stakeholder_task.write({"name": "Changed"})
        with self.assertRaises(AccessError):
            self.env["project.task"].with_user(self.stakeholder).create({
                "name": "Forbidden",
                "project_id": self.project.id,
            })

    def test_agile_board_shows_done_and_hides_stakeholder_create(self):
        manager_action = self.project.with_user(self.manager).action_view_tasks()
        self.assertNotIn("search_default_open_tasks", manager_action["context"])
        self.assertFalse(manager_action["context"]["agile_scrum_mode"])
        self.assertNotIn(
            "search_default_agile_active_sprint", manager_action["context"]
        )
        stakeholder_action = self.project.with_user(
            self.stakeholder
        ).action_view_tasks()
        for permission in ("create", "edit", "delete"):
            self.assertFalse(stakeholder_action["context"][permission])

        native_project = self.env["project.project"].create({
            "name": "Native action",
        })
        native_action = native_project.action_view_tasks()
        self.assertEqual(
            native_action["context"]["search_default_open_tasks"], 1
        )

    def test_new_issue_cannot_import_into_later_stage(self):
        with self.assertRaises(ValidationError):
            self.env["project.task"].create({
                "name": "Imported into review",
                "project_id": self.project.id,
                "stage_id": self.stages["review"].id,
            })

    def test_stage_from_another_project_is_rejected(self):
        other_project = self.env["project.project"].create({
            "name": "Other Workflow",
            "agile_enabled": True,
            "agile_key": "OTHER",
        })
        other_ready = other_project.type_ids.filtered(
            lambda stage: stage.agile_status == "ready"
        )
        task = self._new_issue()
        with self.assertRaises(ValidationError):
            task.with_user(self.manager).write({"stage_id": other_ready.id})

    def test_archived_stage_preserves_history_and_blocks_transitions(self):
        task = self._new_issue()
        backlog = task.stage_id
        ready = self.stages["ready"]

        ready.with_user(self.manager).write({"active": False})
        self.assertEqual(task.stage_id, backlog)
        with self.assertRaisesRegex(UserError, "stage is archived"):
            task.with_user(self.contributor).action_agile_mark_ready()

        with self.assertRaisesRegex(UserError, "stage is archived"):
            task.with_user(self.manager).write({"stage_id": ready.id})

        ready.with_user(self.manager).write({"active": True})
        task.with_user(self.contributor).action_agile_mark_ready()
        self.assertEqual(task.stage_id, ready)

    def test_archived_backlog_prevents_silent_issue_creation(self):
        backlog = self.stages["backlog"]
        backlog.with_user(self.manager).write({"active": False})
        with self.assertRaisesRegex(ValidationError, "Backlog stage is archived"):
            self.env["project.task"].create({
                "name": "Cannot create without Backlog",
                "project_id": self.project.id,
            })

    def test_start_requires_assignee_and_accepts_same_write_assignment(self):
        task = self._new_issue()
        task.write({"user_ids": [Command.clear()]})
        task.with_user(self.contributor).action_agile_mark_ready()

        with self.assertRaisesRegex(UserError, "add an assignee"):
            task.with_user(self.contributor).action_agile_start()
        self.assertEqual(task.agile_status, "ready")

        task.with_user(self.manager).write({
            "stage_id": self.stages["progress"].id,
            "user_ids": [Command.set([self.contributor.id])],
        })
        self.assertEqual(task.agile_status, "progress")
        self.assertEqual(task.user_ids, self.contributor)

    def test_review_and_done_require_assignee_and_description(self):
        task = self._new_issue()
        manager_task = task.with_user(self.manager)
        manager_task.action_agile_mark_ready()
        manager_task.action_agile_start()
        manager_task.write({"description": "<p><br></p>"})

        with self.assertRaisesRegex(UserError, "add a description"):
            manager_task.action_agile_send_review()
        self.assertEqual(task.agile_status, "progress")

        manager_task.write({
            "stage_id": self.stages["review"].id,
            "description": "Ready for QA.",
        })
        manager_task.write({"user_ids": [Command.clear()]})
        with self.assertRaisesRegex(UserError, "add an assignee"):
            manager_task.action_agile_complete()
        self.assertEqual(task.agile_status, "review")

    def test_cancel_does_not_require_delivery_fields(self):
        task = self._new_issue()
        task.write({
            "user_ids": [Command.clear()],
            "description": False,
        })
        task.with_user(self.manager).action_agile_cancel()
        self.assertEqual(task.agile_status, "canceled")

    def test_transition_posts_history(self):
        task = self._new_issue()
        task.message_subscribe(partner_ids=self.reviewer.partner_id.ids)
        task.message_unsubscribe(partner_ids=self.reviewer.partner_id.ids)
        previous_messages = task.message_ids
        task.with_user(self.contributor).action_agile_mark_ready()
        self.env.flush_all()
        self.env.cr.precommit.run()
        task.invalidate_recordset(["message_ids"])
        new_messages = task.message_ids - previous_messages
        self.assertEqual(len(new_messages), 1)
        self.assertIn(
            "stage_id",
            new_messages.tracking_value_ids.field_id.mapped("name"),
        )
        reviewer_notifications = self.env["mail.notification"].search([
            ("mail_message_id", "in", new_messages.ids),
            ("res_partner_id", "=", self.reviewer.partner_id.id),
        ])
        self.assertFalse(reviewer_notifications)

    def test_native_project_behavior_is_unchanged(self):
        project = self.env["project.project"].create({"name": "Native"})
        stage = self.env["project.task.type"].create({
            "name": "Native Done",
            "project_ids": [Command.link(project.id)],
        })
        task = self.env["project.task"].create({
            "name": "Native task",
            "project_id": project.id,
        })
        task.write({"stage_id": stage.id, "state": "1_done"})
        self.assertFalse(task.issue_key)
        self.assertFalse(task.agile_status)
        self.assertEqual(task.state, "1_done")
        self.assertFalse(task.agile_is_blocked)

    def test_contributor_cannot_mutate_agile_workflow_configuration(self):
        member_role = self.project._agile_role_for_user(self.contributor)
        self.assertEqual(member_role, "contributor")
        Stage = self.env["project.task.type"].with_user(self.contributor)

        with self.assertRaises(AccessError):
            Stage.create({
                "name": "Contributor-created Agile stage",
                "project_ids": [Command.link(self.project.id)],
            })

        backlog = self.stages["backlog"].with_user(self.contributor)
        with self.assertRaises(AccessError):
            backlog.write({"name": "Contributor-renamed Backlog"})
        with self.assertRaises(AccessError):
            backlog.unlink()

    def test_manual_block_requires_reason_and_can_be_cleared(self):
        task = self._new_issue()
        contributor_task = task.with_user(self.contributor)
        previous_messages = task.message_ids
        with self.assertRaisesRegex(ValidationError, "Add a short reason"):
            contributor_task.write({"agile_blocked": True})
        with self.assertRaisesRegex(ValidationError, "only be saved while"):
            contributor_task.write({"agile_block_reason": "Orphan reason"})
        with self.assertRaises(ValidationError):
            contributor_task.write({
                "agile_blocked": True,
                "agile_block_reason": "   ",
            })

        contributor_task.write({
            "agile_blocked": True,
            "agile_block_reason": "Waiting on design approval",
        })
        self.assertTrue(task.agile_is_blocked)
        self.assertEqual(
            task.agile_block_reason_display, "Waiting on design approval"
        )
        self.env.flush_all()
        self.env.cr.precommit.run()
        new_messages = task.message_ids - previous_messages
        tracked_fields = new_messages.tracking_value_ids.field_id.mapped(
            "field_description"
        )
        self.assertTrue(
            {"Mark as blocked", "Block reason"}.issubset(set(tracked_fields))
        )
        contributor_task.write({"agile_blocked": False})
        self.assertFalse(task.agile_is_blocked)
        self.assertFalse(task.agile_block_reason)

    def test_native_dependency_is_shown_as_agile_block(self):
        self.project.write({"allow_task_dependencies": True})
        blocker = self._new_issue("Predecessor")
        task = self._new_issue("Waiting issue")
        task.with_user(self.manager).write({
            "depend_on_ids": [Command.link(blocker.id)],
        })
        self.assertEqual(task.state, "04_waiting_normal")
        self.assertTrue(task.agile_is_blocked)
        self.assertEqual(task.agile_block_reason_display, "Waiting for dependencies")

        blocker.with_context(agile_workflow_setup=True).write({
            "stage_id": self.stages["done"].id,
            "state": "1_done",
        })
        self.assertEqual(task.state, "01_in_progress")
        self.assertFalse(task.agile_is_blocked)

    def test_stakeholder_cannot_change_block_status(self):
        task = self._new_issue()
        self.assertTrue(task.with_user(self.manager).can_agile_update_block)
        self.assertTrue(task.with_user(self.contributor).can_agile_update_block)
        self.assertFalse(task.with_user(self.reviewer).can_agile_update_block)
        with self.assertRaises(AccessError):
            task.with_user(self.stakeholder).write({
                "agile_blocked": True,
                "agile_block_reason": "Hidden reason",
            })
        with self.assertRaises(AccessError):
            task.with_user(self.reviewer).write({
                "agile_blocked": True,
                "agile_block_reason": "Reviewers do not triage blockers",
            })
        self.assertFalse(task.with_user(self.stakeholder).can_agile_update_block)

    def test_block_controls_are_present_in_agile_views(self):
        form = self.env.ref("agile_community.view_project_task_form_agile")
        kanban = self.env.ref("agile_community.project_task_kanban_agile")
        search = self.env.ref("agile_community.project_task_search_agile")
        self.assertIn("agile_block_reason", form.arch)
        self.assertIn("agile_is_blocked", kanban.arch)
        self.assertIn("Blocked", kanban.arch)
        self.assertIn("agile_is_blocked", search.arch)

    def test_workflow_view_has_plain_language_actions(self):
        view = self.env.ref("agile_community.view_project_task_form_agile")
        for action in [
            "action_agile_mark_ready",
            "action_agile_start",
            "action_agile_send_review",
            "action_agile_return",
            "action_agile_complete",
            "action_agile_reopen",
            "action_agile_cancel",
        ]:
            self.assertIn(action, view.arch)
