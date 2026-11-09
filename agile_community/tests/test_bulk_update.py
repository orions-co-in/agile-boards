from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, new_test_user


class TestAgileBulkUpdate(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(
            cls.env,
            login="bulk_manager",
            groups="project.group_project_manager",
        )
        cls.contributor = new_test_user(
            cls.env,
            login="bulk_contributor",
            groups="project.group_project_user",
        )
        cls.stakeholder = new_test_user(
            cls.env,
            login="bulk_stakeholder",
            groups="project.group_project_user,agile_community.group_agile_stakeholder",
        )
        cls.project_a = cls.env["project.project"].create({
            "name": "Bulk A",
            "privacy_visibility": "employees",
            "user_id": cls.manager.id,
            "agile_enabled": True,
            "agile_key": "BULA",
            "agile_method": "kanban",
        })
        cls.project_b = cls.env["project.project"].create({
            "name": "Bulk B",
            "privacy_visibility": "employees",
            "user_id": cls.manager.id,
            "agile_enabled": True,
            "agile_key": "BULB",
        })
        cls.scrum_project = cls.env["project.project"].create({
            "name": "Bulk Scrum",
            "privacy_visibility": "employees",
            "user_id": cls.manager.id,
            "agile_enabled": True,
            "agile_key": "BULS",
            "use_scrum": True,
        })
        cls.scrum_project_b = cls.env["project.project"].create({
            "name": "Bulk Scrum B",
            "privacy_visibility": "employees",
            "user_id": cls.manager.id,
            "agile_enabled": True,
            "agile_key": "BULT",
            "use_scrum": True,
        })
        cls.scrum_sprint = cls.env["project.sprint"].create({
            "name": "Bulk Target Sprint",
            "project_id": cls.scrum_project.id,
            "date_start": "2026-09-01",
            "date_end": "2026-09-14",
        })

    def _issue(self, project, title):
        return self.env["project.task"].create({
            "name": title,
            "project_id": project.id,
            "description": "Bulk update test issue.",
        })

    def _wizard(self, tasks, **values):
        return self.env["agile_community.bulk_update_wizard"].create({
            "task_ids": [Command.set(tasks.ids)],
            **values,
        })

    def test_bulk_editor_previews_impacted_issues_and_revalidates_on_apply(self):
        issue = self._issue(self.project_a, "Preview update")
        wizard = self._wizard(
            issue,
            update_assignees=True,
            assignee_operation="replace",
            assignee_ids=[Command.set(self.contributor.ids)],
        )
        preview = wizard.with_user(self.manager).preview_result
        self.assertIn(issue.issue_key, preview)
        self.assertIn("Set assignees to", preview)
        self.assertIn("Can be updated", preview)
        wizard.with_user(self.manager).action_apply()
        self.assertEqual(issue.user_ids, self.contributor)

    def test_bulk_editor_changes_priority_points_version_epic_and_status(self):
        # NU-13: the editor offered only assignees, labels and sprint.
        issues = self._issue(self.project_a, "One") | self._issue(self.project_a, "Two")
        epic = self.env["project.task"].create({
            "name": "An epic", "project_id": self.project_a.id, "agile_is_epic": True,
            "description": "Epic.",
        })
        version = self.env["project.version"].create({"name": "2.0", "project_id": self.project_a.id})
        ready = self.env["project.task.type"]._agile_main_stage(self.project_a, "ready")
        wizard = self._wizard(
            issues,
            update_priority=True, priority="2",
            update_points=True, story_points=8.0,
            update_version=True, version_id=version.id,
            update_epic=True, epic_id=epic.id,
            update_status=True, stage_id=ready.id,
        )
        preview = wizard.with_user(self.manager).preview_result
        for text in ("Set priority", "Set points to 8.0", "Set fix version to 2.0", "Set epic to", "Move issues to status"):
            self.assertIn(text, preview)
        wizard.with_user(self.manager).action_apply()
        for issue in issues:
            self.assertEqual(issue.priority, "2")
            self.assertEqual(issue.story_points, 8.0)
            self.assertEqual(issue.version_id, version)
            self.assertEqual(issue.parent_id, epic)
            self.assertEqual(issue.stage_id, ready)

    def test_bulk_editor_refuses_a_status_change_the_workflow_forbids(self):
        issue = self._issue(self.project_a, "Stuck")
        done = self.env["project.task.type"]._agile_main_stage(self.project_a, "done")
        wizard = self._wizard(issue, update_status=True, stage_id=done.id)
        with self.assertRaises(UserError):
            wizard.with_user(self.contributor).action_apply()

    def test_selection_action_is_only_for_agile_issues_and_checks_role(self):
        first = self._issue(self.project_a, "One")
        second = self._issue(self.project_b, "Two")
        action = (first | second).with_user(self.contributor).action_open_agile_bulk_update()
        self.assertEqual(action["res_model"], "agile_community.bulk_update_wizard")
        self.assertEqual(action["context"]["default_task_ids"], [Command.set((first | second).ids)])

        bulk_action = self.env.ref("agile_community.action_agile_bulk_update_wizard")
        manager_actions = self.env["ir.actions.actions"].with_user(
            self.manager
        ).get_bindings("project.task")["action"]
        contributor_actions = self.env["ir.actions.actions"].with_user(
            self.contributor
        ).get_bindings("project.task")["action"]
        self.assertIn(bulk_action.display_name, [action["name"] for action in manager_actions])
        self.assertIn(bulk_action.display_name, [action["name"] for action in contributor_actions])
        native_project = self.env["project.project"].create({"name": "Native"})
        native_task = self._issue(native_project, "Not Agile")
        with self.assertRaisesRegex(UserError, "not an Agile issue"):
            (first | native_task).with_user(self.manager).action_open_agile_bulk_update()
        with self.assertRaisesRegex(UserError, "only Agile team members"):
            first.with_user(self.stakeholder).action_open_agile_bulk_update()

    def test_cross_project_bulk_assign_and_add_shared_label(self):
        first = self._issue(self.project_a, "One")
        second = self._issue(self.project_b, "Two")
        label = self.env["project.tags"].create({"name": "Shared QA label"})
        wizard = self._wizard(
            first | second,
            update_assignees=True,
            assignee_operation="replace",
            assignee_ids=[Command.set(self.contributor.ids)],
            update_tags=True,
            tag_operation="add",
            tag_ids=[Command.set(label.ids)],
        )

        wizard.with_user(self.manager).action_apply()

        self.assertEqual(first.user_ids, self.contributor)
        self.assertEqual(second.user_ids, self.contributor)
        self.assertEqual(first.tag_ids, label)
        self.assertEqual(second.tag_ids, label)

    def test_project_specific_label_error_is_actionable_and_atomic(self):
        first = self._issue(self.project_a, "One")
        second = self._issue(self.project_b, "Two")
        label = self.env["project.tags"].create({
            "name": "A-only label",
            "project_ids": [Command.set(self.project_a.ids)],
        })
        wizard = self._wizard(
            first | second,
            update_tags=True,
            tag_operation="add",
            tag_ids=[Command.set(label.ids)],
        )

        with self.assertRaises(UserError) as raised:
            wizard.with_user(self.manager).action_apply()

        self.assertIn(second.issue_key, str(raised.exception))
        self.assertIn("not available in project", str(raised.exception))
        self.assertFalse(first.tag_ids)
        self.assertFalse(second.tag_ids)

    def test_native_issue_in_bulk_selection_prevents_all_changes(self):
        agile_task = self._issue(self.project_a, "Agile")
        native_project = self.env["project.project"].create({"name": "Native"})
        native_task = self._issue(native_project, "Native task")
        label = self.env["project.tags"].create({"name": "No partial"})
        wizard = self._wizard(
            agile_task | native_task,
            update_tags=True,
            tag_operation="add",
            tag_ids=[Command.set(label.ids)],
        )

        with self.assertRaisesRegex(UserError, "not an Agile issue"):
            wizard.with_user(self.manager).action_apply()

        self.assertFalse(agile_task.tag_ids)
        self.assertFalse(native_task.tag_ids)

    def test_stakeholder_cannot_apply_bulk_update(self):
        task = self._issue(self.project_a, "Read only")
        label = self.env["project.tags"].create({"name": "Denied"})
        wizard = self._wizard(
            task,
            update_tags=True,
            tag_operation="add",
            tag_ids=[Command.set(label.ids)],
        )

        with self.assertRaisesRegex(UserError, "only Agile team members"):
            wizard.with_user(self.stakeholder).action_apply()
        self.assertFalse(task.tag_ids)

    def test_add_and_remove_operations_preserve_other_values(self):
        task = self._issue(self.project_a, "Operations")
        existing_user = self.env.user
        first_label = self.env["project.tags"].create({"name": "Keep this label"})
        remove_label = self.env["project.tags"].create({"name": "Remove this label"})
        added_label = self.env["project.tags"].create({"name": "Add this label"})
        task.write({
            "user_ids": [Command.set(existing_user.ids)],
            "tag_ids": [Command.set((first_label | remove_label).ids)],
        })
        self._wizard(
            task,
            update_assignees=True,
            assignee_operation="add",
            assignee_ids=[Command.set(self.contributor.ids)],
            update_tags=True,
            tag_operation="remove",
            tag_ids=[Command.set(remove_label.ids)],
        ).with_user(self.manager).action_apply()
        self.assertEqual(task.user_ids, existing_user | self.contributor)
        self.assertEqual(task.tag_ids, first_label)

        self._wizard(
            task,
            update_tags=True,
            tag_operation="add",
            tag_ids=[Command.set(added_label.ids)],
        ).with_user(self.manager).action_apply()
        self.assertEqual(task.tag_ids, first_label | added_label)

    def test_bulk_sprint_change_can_assign_and_return_to_backlog(self):
        tasks = self._issue(self.scrum_project, "One") | self._issue(
            self.scrum_project, "Two"
        )
        wizard = self._wizard(
            tasks,
            update_sprint=True,
            sprint_operation="move",
            sprint_id=self.scrum_sprint.id,
        )

        wizard.with_user(self.manager).action_apply()

        self.assertEqual(tasks.mapped("sprint_id"), self.scrum_sprint)
        self._wizard(
            tasks, update_sprint=True, sprint_operation="backlog"
        ).with_user(self.manager).action_apply()
        self.assertFalse(tasks.mapped("sprint_id"))

    def test_bulk_sprint_change_reports_mismatched_projects_atomically(self):
        first = self._issue(self.scrum_project, "First Scrum issue")
        second = self._issue(self.scrum_project_b, "Other Scrum issue")
        wizard = self._wizard(
            first | second,
            update_sprint=True,
            sprint_operation="move",
            sprint_id=self.scrum_sprint.id,
        )

        with self.assertRaises(UserError) as raised:
            wizard.with_user(self.manager).action_apply()

        self.assertIn(second.issue_key, str(raised.exception))
        self.assertIn("belongs to another project", str(raised.exception))
        self.assertFalse(first.sprint_id)
        self.assertFalse(second.sprint_id)

    def test_bulk_sprint_change_rejects_non_scrum_issue_without_partial_write(self):
        scrum_task = self._issue(self.scrum_project, "Scrum issue")
        ordinary_agile_task = self._issue(self.project_a, "Agile Kanban issue")
        wizard = self._wizard(
            scrum_task | ordinary_agile_task,
            update_sprint=True,
            sprint_operation="move",
            sprint_id=self.scrum_sprint.id,
        )

        with self.assertRaises(UserError) as raised:
            wizard.with_user(self.manager).action_apply()

        self.assertIn(ordinary_agile_task.issue_key, str(raised.exception))
        self.assertIn("Scrum-enabled", str(raised.exception))
        self.assertFalse(scrum_task.sprint_id)
        self.assertFalse(ordinary_agile_task.sprint_id)

    def test_bulk_sprint_change_requires_target_for_move_and_operation(self):
        task = self._issue(self.scrum_project, "Validation issue")
        no_operation = self._wizard(task, update_sprint=False)
        with self.assertRaisesRegex(UserError, "Choose whether to change"):
            no_operation.with_user(self.manager).action_apply()

        no_target = self._wizard(
            task, update_sprint=True, sprint_operation="move"
        )
        with self.assertRaisesRegex(UserError, "Select a destination sprint"):
            no_target.with_user(self.manager).action_apply()
        self.assertFalse(task.sprint_id)

    def test_bulk_sprint_change_rejects_stale_membership_without_writing(self):
        task = self._issue(self.scrum_project, "Concurrent move")
        wizard = self._wizard(
            task,
            update_sprint=True,
            sprint_operation="move",
            sprint_id=self.scrum_sprint.id,
        )
        task.write({"sprint_id": self.scrum_sprint.id})

        with self.assertRaisesRegex(UserError, "membership changed after this editor opened"):
            wizard.with_user(self.manager).action_apply()

        self.assertEqual(task.sprint_id, self.scrum_sprint)

    def test_sprint_membership_snapshot_cannot_be_overridden_by_client(self):
        task = self._issue(self.scrum_project, "Protected snapshot")
        wizard = self._wizard(
            task,
            update_sprint=True,
            sprint_operation="move",
            sprint_id=self.scrum_sprint.id,
        )

        with self.assertRaisesRegex(AccessError, "system managed"):
            wizard.with_user(self.manager).with_context(
                internal_sprint_snapshot=True
            ).write({"sprint_membership_snapshot": {}})

    def test_selected_issues_cannot_be_changed_after_preview_opens(self):
        issue = self._issue(self.project_a, "Locked preview selection")
        other_issue = self._issue(self.project_a, "Not in preview")
        wizard = self._wizard(
            issue,
            update_tags=True,
            tag_operation="add",
            tag_ids=[Command.clear()],
        )

        with self.assertRaisesRegex(AccessError, "selected issue set"):
            wizard.write({"task_ids": [Command.set(other_issue.ids)]})

    def test_large_issue_lists_page_without_overlap_or_gaps(self):
        tasks = self.env["project.task"]
        self.env["project.task"].create([
            {
                "name": "Paged issue %02d" % index,
                "project_id": self.scrum_project.id,
            }
            for index in range(41)
        ])
        domain = [("project_id", "=", self.scrum_project.id)]
        expected = tasks.search(domain, order="id").ids
        page_size = 9
        pages = [
            tasks.search(domain, order="id", limit=page_size, offset=offset).ids
            for offset in range(0, len(expected), page_size)
        ]

        self.assertGreater(len(pages), 4)
        self.assertEqual([task_id for page in pages for task_id in page], expected)
        self.assertEqual(sum(map(len, pages)), len(set(expected)))
