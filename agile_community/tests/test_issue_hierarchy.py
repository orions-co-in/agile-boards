from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user


class TestAgileIssueHierarchy(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(
            cls.env,
            login="hierarchy_manager",
            groups="project.group_project_manager",
        )
        cls.contributor = new_test_user(
            cls.env,
            login="hierarchy_contributor",
            groups="project.group_project_user",
        )
        cls.stakeholder = new_test_user(
            cls.env,
            login="hierarchy_stakeholder",
            groups="project.group_project_user,agile_community.group_agile_stakeholder",
        )
        cls.project = cls.env["project.project"].create({
            "name": "Issue hierarchy",
            "privacy_visibility": "employees",
            "user_id": cls.manager.id,
            "agile_enabled": True,
            "agile_key": "HIER",
            "use_scrum": True,
        })
        cls.types = {
            record.name: record
            for record in cls.env["agile_community.task_type"].search([])
        }

    def _issue(self, name, task_type="Task", project=None, **values):
        return self.env["project.task"].create({
            "name": name,
            "project_id": (project or self.project).id,
            "agile_task_type_id": self.types[task_type].id,
            "description": "A short issue description.",
            **values,
        })

    def test_epic_child_progress_and_story_points_roll_up_without_cascade(self):
        epic = self._issue("Epic", "Epic")
        story = self._issue(
            "Story", "Story", parent_id=epic.id,
            story_points=5, story_points_estimated=True,
        )
        self._issue("Unestimated story", "Story", parent_id=epic.id)
        canceled = self._issue(
            "Canceled story", "Story", parent_id=epic.id,
            story_points=8, story_points_estimated=True,
        )
        canceled.with_user(self.manager).action_agile_cancel()
        done = self.project.type_ids.filtered(
            lambda stage: stage.agile_status == "done"
        )

        self.assertEqual(epic.agile_child_issue_count, 3)
        self.assertEqual(epic.agile_child_done_count, 0)
        self.assertEqual(epic.agile_child_points, 5.0)
        self.assertEqual(epic.agile_child_unestimated_count, 1)

        epic.with_context(agile_workflow_setup=True).write({"stage_id": done.id})
        self.assertEqual(epic.agile_status, "done")
        self.assertEqual(story.agile_status, "backlog")
        self.assertEqual(epic.agile_child_done_count, 0)

        epic.with_user(self.manager).action_archive()
        self.assertFalse(epic.active)
        self.assertTrue(story.active)

    def test_issue_hierarchy_reads_keep_visible_links_and_native_tasks(self):
        epic = self._issue("Readable epic", "Epic")
        story = self._issue("Readable story", "Story", parent_id=epic.id)

        visible_children = epic.with_user(self.contributor).read(["child_ids"])[0][
            "child_ids"
        ]
        self.assertIn(
            story.id, visible_children,
        )
        visible_parent = story.with_user(self.contributor).read(["parent_id"])[0][
            "parent_id"
        ]
        self.assertEqual(
            visible_parent[0], epic.id,
        )

        native_project = self.env["project.project"].create({
            "name": "Native hierarchy", "privacy_visibility": "employees",
        })
        native_parent = self.env["project.task"].create({
            "name": "Native parent", "project_id": native_project.id,
        })
        native_child = self.env["project.task"].create({
            "name": "Native child",
            "project_id": native_project.id,
            "parent_id": native_parent.id,
        })
        self.assertEqual(
            native_parent.with_user(self.contributor).read(["child_ids"])[0][
                "child_ids"
            ],
            [native_child.id],
        )

    def test_epic_type_cannot_be_a_subtask_and_hierarchy_has_two_levels(self):
        story = self._issue("Story", "Story")
        with self.assertRaisesRegex(ValidationError, "Epic cannot be a subtask"):
            self._issue("Nested epic", "Epic", parent_id=story.id)

        epic = self._issue("Epic", "Epic")
        story = self._issue("Epic story", "Story", parent_id=epic.id)
        subtask = self._issue("Implementation", "Task", parent_id=story.id)
        with self.assertRaisesRegex(ValidationError, "one subtask level"):
            self._issue("Nested implementation", "Task", parent_id=subtask.id)

    def test_parent_cycle_is_rejected_by_native_project_hierarchy(self):
        first = self._issue("First")
        second = self._issue("Second", parent_id=first.id)
        with self.assertRaisesRegex(ValidationError, "recursive hierarchy"):
            first.write({"parent_id": second.id})

    def test_parent_must_be_in_same_agile_project(self):
        second_project = self.env["project.project"].create({
            "name": "Other issue hierarchy",
            "privacy_visibility": "employees",
            "agile_enabled": True,
            "agile_key": "HIER2",
        })
        other_epic = self._issue("Other epic", "Epic", project=second_project)
        with self.assertRaisesRegex(ValidationError, "same Agile project"):
            self._issue("Wrong child", "Story", parent_id=other_epic.id)

    def test_native_blockers_are_directional_and_cycles_are_rejected(self):
        self.project.write({"allow_task_dependencies": True})
        blocker = self._issue("Blocker")
        blocked = self._issue("Blocked")
        blocked.write({"depend_on_ids": [Command.link(blocker.id)]})
        self.assertIn(blocked, blocker.dependent_ids)
        self.assertIn(blocker, blocked.depend_on_ids)
        self.assertTrue(blocked.agile_is_blocked)

        with self.assertRaises(ValidationError):
            blocker.write({"depend_on_ids": [Command.link(blocked.id)]})

    def test_agile_dependency_cannot_link_to_normal_task(self):
        self.project.write({"allow_task_dependencies": True})
        agile_issue = self._issue("Agile issue")
        native_project = self.env["project.project"].create({"name": "Native"})
        native_task = self.env["project.task"].create({
            "name": "Native blocker", "project_id": native_project.id,
        })
        with self.assertRaisesRegex(
            ValidationError, "Agile blockers can only link to other Agile issues"
        ):
            agile_issue.write({"depend_on_ids": [Command.link(native_task.id)]})

    def test_agile_dependency_cannot_cross_company(self):
        company = self.env["res.company"].create({"name": "Other dependency company"})
        projects = self.env["project.project"].with_context(
            allowed_company_ids=(self.env.company | company).ids
        )
        other_project = projects.create({
            "name": "Other dependency Agile",
            "company_id": company.id,
            "agile_enabled": True,
            "agile_key": "HIER5",
            "allow_task_dependencies": True,
        })
        self.project.write({"allow_task_dependencies": True})
        issue = self._issue("Company-bound issue")
        blocker = self._issue("Other-company blocker", project=other_project)
        with self.assertRaisesRegex(ValidationError, "different companies"):
            issue.write({"depend_on_ids": [Command.link(blocker.id)]})

    def test_related_and_duplicate_links_are_symmetric_and_distinct(self):
        first = self._issue("First")
        second = self._issue("Second")

        first.write({"agile_related_issue_ids": [Command.link(second.id)]})
        self.assertEqual(first.agile_related_issue_ids, second)
        self.assertEqual(second.agile_related_issue_ids, first)

        second.write({"agile_duplicate_issue_ids": [Command.link(first.id)]})
        self.assertEqual(first.agile_duplicate_issue_ids, second)
        self.assertEqual(second.agile_duplicate_issue_ids, first)
        self.assertEqual(
            self.env["agile_community.issue_link"].sudo().search_count([
                ("issue_a_id", "in", (first | second).ids),
            ]),
            2,
        )

    def test_self_link_and_mixed_agile_native_link_are_rejected(self):
        issue = self._issue("Issue")
        with self.assertRaisesRegex(ValidationError, "cannot be linked to itself"):
            issue.write({"agile_duplicate_issue_ids": [Command.link(issue.id)]})

        native_project = self.env["project.project"].create({"name": "Native"})
        native_task = self.env["project.task"].create({
            "name": "Native task", "project_id": native_project.id,
        })
        with self.assertRaisesRegex(ValidationError, "Only Agile issues"):
            issue.write({"agile_related_issue_ids": [Command.link(native_task.id)]})

    def test_cross_company_link_is_rejected(self):
        company = self.env["res.company"].create({"name": "Other company"})
        with_company = self.env["project.project"].with_context(
            allowed_company_ids=(self.env.company | company).ids
        )
        other_project = with_company.create({
            "name": "Other company Agile",
            "company_id": company.id,
            "agile_enabled": True,
            "agile_key": "HIER3",
        })
        first = self._issue("Company issue")
        other = self._issue("Other company issue", project=other_project)
        with self.assertRaisesRegex(ValidationError, "different companies"):
            first.write({"agile_related_issue_ids": [Command.link(other.id)]})

    def test_cross_project_link_requires_access_to_both_issues(self):
        private_project = self.env["project.project"].create({
            "name": "Private issue project",
            "privacy_visibility": "employees",
            "agile_enabled": True,
            "agile_key": "HIER4",
        })
        source = self._issue("Visible source")
        hidden_target = self._issue("Hidden target", project=private_project)
        private_project.write({"privacy_visibility": "followers"})
        self.assertFalse(hidden_target.with_user(self.contributor).has_access("read"))
        self.assertFalse(private_project.with_user(self.contributor).has_access("read"))
        with self.assertRaises(AccessError):
            source.with_user(self.contributor).write({
                "agile_related_issue_ids": [Command.link(hidden_target.id)],
            })
        source.write({"agile_related_issue_ids": [Command.link(hidden_target.id)]})
        self.assertNotIn(
            hidden_target,
            source.with_user(self.contributor).agile_related_issue_ids,
        )

    def test_cross_project_blocker_requires_visibility_of_both_projects(self):
        private_project = self.env["project.project"].create({
            "name": "Private blocker project",
            "privacy_visibility": "employees",
            "agile_enabled": True,
            "agile_key": "HIER6",
            "allow_task_dependencies": True,
        })
        self.project.write({"allow_task_dependencies": True})
        blocked = self._issue("Blocked in visible project")
        blocker = self._issue("Hidden-project blocker", project=private_project)
        hidden_blocker = self._issue("Second hidden blocker", project=private_project)
        blocked.write({"depend_on_ids": [Command.link(blocker.id)]})
        private_project.write({"privacy_visibility": "followers"})

        self.assertFalse(blocker.with_user(self.contributor).has_access("read"))
        self.assertFalse(private_project.with_user(self.contributor).has_access("read"))
        self.assertIn(blocker, blocked.sudo().depend_on_ids)
        self.assertFalse(blocked.with_user(self.contributor)._agile_can_read_task_link(
            blocked.sudo(), blocker.sudo()
        ))
        self.assertEqual(
            blocked.with_user(self.contributor).read(["depend_on_ids"])[0]["depend_on_ids"],
            [],
        )
        with self.assertRaises(AccessError):
            blocker.with_user(self.contributor).read(["dependent_ids"])
        self.contributor.write({
            "group_ids": [
                Command.link(self.env.ref("base.group_allow_export").id)
            ],
        })
        with self.assertRaisesRegex(AccessError, "dependencies that you cannot view"):
            blocked.with_user(self.contributor).export_data(["depend_on_ids"])
        with self.assertRaises(AccessError):
            blocked.with_user(self.contributor).write({
                "depend_on_ids": [Command.link(hidden_blocker.id)],
            })

    def test_stakeholder_cannot_change_links_and_deleted_targets_disappear(self):
        first = self._issue("First")
        second = self._issue("Second")
        with self.assertRaises(AccessError):
            first.with_user(self.stakeholder).write({
                "agile_related_issue_ids": [Command.link(second.id)],
            })
        with self.assertRaises(AccessError):
            self.env["agile_community.issue_link"].with_user(
                self.contributor
            ).search([])

        first.write({"agile_related_issue_ids": [Command.link(second.id)]})
        second.unlink()
        first.invalidate_recordset(["agile_related_issue_ids"])
        self.assertFalse(first.agile_related_issue_ids)

    def test_normal_project_parent_tasks_keep_native_behavior(self):
        project = self.env["project.project"].create({"name": "Native parent"})
        parent = self.env["project.task"].create({
            "name": "Parent", "project_id": project.id,
        })
        child = self.env["project.task"].create({
            "name": "Child", "project_id": project.id, "parent_id": parent.id,
        })
        self.assertEqual(child.parent_id, parent)
        self.assertFalse(child.agile_project_enabled)
        parent.action_archive()
        self.assertFalse(parent.active)
        self.assertFalse(child.active)
