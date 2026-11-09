from odoo.addons.base.tests.common import BaseCommon
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from psycopg2 import IntegrityError


@tagged("post_install", "-at_install")
class TestProjectSprint(BaseCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user_demo = cls._create_new_internal_user(
            login="scrum_sprint_user",
            groups="project.group_project_user",
        )
        cls.user_admin = cls.env.ref("base.user_admin")
        cls.project = cls.env["project.project"].create(
            {"name": "Test Project", "user_id": cls.user_demo.id, "use_scrum": True}
        )
        cls.sprint = cls.env["project.sprint"].create(
            {
                "name": "Test Sprint",
                "user_ids": [(4, cls.user_demo.id)],
                "project_id": cls.project.id,
                "date_start": "2024-08-28",
                "date_end": "2024-09-15",
            }
        )
        cls.task = cls.env["project.task"].create(
            {
                "name": "Test Task",
                "project_id": cls.project.id,
                "user_ids": [(4, cls.user_demo.id)],
                "sprint_id": cls.sprint.id,
            }
        )

    def test_state_project_sprint(self):
        self.assertEqual(self.sprint.state, "draft")
        with self.assertRaises(UserError):
            self.sprint.action_start()
        self.sprint.action_confirm_plan()
        self.assertEqual(self.sprint.committed_task_count, 1)
        self.assertEqual(len(self.sprint.commitment_ids), 1)
        self.sprint.action_start()
        self.assertEqual(self.sprint.state, "in_progress")
        with self.assertRaises(UserError):
            self.sprint.action_done()
        self.task.sprint_id = False
        self.sprint.action_done()
        self.assertEqual(self.sprint.state, "done")
        with self.assertRaises(UserError):
            self.sprint.write({"name": "Changed after completion"})

    def test_only_one_active_sprint_per_project(self):
        sprint_2 = self.env["project.sprint"].create(
            {
                "name": "Test Sprint 2",
                "project_id": self.project.id,
                "date_start": "2024-08-10",
                "date_end": "2024-08-28",
            }
        )
        self.sprint.action_confirm_plan()
        self.sprint.action_start()
        with self.assertRaises(UserError):
            sprint_2.action_start()
        self.assertEqual(sprint_2.state, "draft")

    def test_task_count(self):
        self.assertEqual(self.sprint.tasks_count, 1)
        self.task.sprint_id = False
        self.sprint._compute_tasks_count()
        self.assertEqual(self.sprint.tasks_count, 0)

    def test_compute_end_date(self):
        self.assertEqual(self.sprint.date_end.strftime("%Y-%m-%d"), "2024-09-15")
        self.sprint.date_option = "1_months"
        self.sprint._compute_date_end()
        self.assertEqual(self.sprint.date_end.strftime("%Y-%m-%d"), "2024-09-28")
        self.sprint.date_option = "custom"
        self.sprint._compute_date_end()
        self.assertEqual(self.sprint.date_end.strftime("%Y-%m-%d"), "2024-08-29")

    def test_date_boundaries_allow_single_day_sprint_and_reject_inverted_dates(self):
        boundary_sprint = self.env["project.sprint"].create(
            {
                "name": "Single-day boundary",
                "project_id": self.project.id,
                "date_start": "2024-03-10",
                "date_end": "2024-03-10",
                "date_option": "custom",
            }
        )
        self.assertEqual(boundary_sprint.date_start, boundary_sprint.date_end)
        with self.cr.savepoint(), self.assertRaises(IntegrityError):
            self.env["project.sprint"].create(
                {
                    "name": "Inverted boundary",
                    "project_id": self.project.id,
                    "date_start": "2024-03-11",
                    "date_end": "2024-03-10",
                    "date_option": "custom",
                }
            )

    def test_action_task(self):
        action = self.sprint.action_tasks()
        self.assertEqual(action["res_model"], "project.task")
        self.assertEqual(action["domain"], [("sprint_id", "=", self.sprint.id)])
        self.assertEqual(
            action["context"],
            {
                "default_project_id": self.project.id,
                "default_sprint_id": self.sprint.id,
            },
        )

    def test_invalid_state_skip_is_rejected(self):
        with self.assertRaises(UserError):
            self.sprint.write({"state": "done"})

    def test_plan_confirmation_is_manager_only_and_snapshots_scope(self):
        with self.assertRaises(UserError):
            self.sprint.with_user(self.user_demo).action_confirm_plan()
        self.sprint.action_confirm_plan()
        snapshot = self.sprint.commitment_ids
        self.assertEqual(snapshot.task_count, 1)
        self.assertEqual(snapshot.line_ids.task_id, self.task)
        self.assertTrue(snapshot.line_ids.issue_key)
        with self.assertRaises(UserError):
            self.sprint.commitment_ids.write({"reason": "tamper"})
        with self.assertRaises(UserError):
            self.sprint.scope_change_ids.write({"reason": "tamper"})
        with self.assertRaises(UserError):
            self.sprint.write({"committed_task_count": 500})
        with self.assertRaises(UserError):
            self.sprint.with_context(skip_sprint_scope_tracking=True).write(
                {"planning_confirmed": False}
            )

    def test_snapshot_retains_issue_identity_after_task_delete(self):
        self.sprint.action_confirm_plan()
        line = self.sprint.commitment_ids.line_ids
        issue_key, task_name = line.issue_key, line.task_name
        self.task.unlink()
        self.assertFalse(line.task_id)
        self.assertEqual(line.issue_key, issue_key)
        self.assertEqual(line.task_name, task_name)

    def test_close_wizard_counts_done_issues_before_the_sprint_closes(self):
        self.sprint.action_confirm_plan()
        self.sprint.action_start()
        wizard = self.env["project.sprint.close"].create({"sprint_id": self.sprint.id})
        self.assertEqual((wizard.committed_count, wizard.done_count), (1, 0))
        self.task.state = "1_done"
        wizard.invalidate_recordset()
        self.assertEqual(wizard.done_count, 1)

    def test_close_wizard_requires_destination_for_unfinished_issue(self):
        self.sprint.action_confirm_plan()
        self.sprint.action_start()
        wizard = self.env["project.sprint.close"].create(
            {"sprint_id": self.sprint.id, "disposition": "sprint"}
        )
        with self.assertRaises(UserError):
            wizard.action_complete()
        self.assertEqual(self.task.sprint_id, self.sprint)
        destination = self.env["project.sprint"].create(
            {
                "name": "Destination Sprint",
                "project_id": self.project.id,
                "date_start": "2024-09-16",
                "date_end": "2024-09-23",
            }
        )
        other_project = self.env["project.project"].create(
            {"name": "Other Scrum Project", "use_scrum": True}
        )
        other_destination = self.env["project.sprint"].create(
            {
                "name": "Wrong Project Sprint",
                "project_id": other_project.id,
                "date_start": "2024-09-16",
                "date_end": "2024-09-23",
            }
        )
        wizard.destination_sprint_id = other_destination
        with self.assertRaises(UserError):
            wizard.action_complete()
        self.assertEqual(self.task.sprint_id, self.sprint)
        wizard.destination_sprint_id = destination
        wizard.action_complete()
        self.assertEqual(self.sprint.state, "done")
        self.assertEqual(self.task.sprint_id, destination)

    def test_close_wizard_can_explicitly_return_unfinished_issues_to_backlog(self):
        self.sprint.action_confirm_plan()
        self.sprint.action_start()
        wizard = self.env["project.sprint.close"].create(
            {"sprint_id": self.sprint.id, "disposition": "backlog"}
        )
        wizard.action_complete()
        self.assertFalse(self.task.sprint_id)
        self.assertEqual(self.sprint.state, "done")

    def test_replan_requires_reason_and_keeps_revision_and_scope_history(self):
        self.sprint.action_confirm_plan()
        task_2 = self.env["project.task"].create(
            {"name": "Added after plan", "project_id": self.project.id, "sprint_id": self.sprint.id}
        )
        with self.assertRaises(ValidationError):
            self.sprint.action_refresh_commitment("")
        self.sprint.action_refresh_commitment("Urgent follow-up")
        self.assertEqual(len(self.sprint.commitment_ids), 2)
        self.assertEqual(self.sprint.commitment_ids.sorted("revision", reverse=True)[0].revision, 2)
        latest = self.sprint.commitment_ids.sorted("revision", reverse=True)[0]
        self.assertEqual(latest.task_count, 2)
        self.assertIn(task_2, latest.line_ids.task_id)
        self.assertEqual(self.sprint.scope_change_ids.filtered(lambda row: row.task_id == task_2).operation, "add")

    def test_close_summary_records_completed_work(self):
        self.sprint.action_confirm_plan()
        self.sprint.action_start()
        self.task.state = "1_done"
        self.sprint.action_done()
        self.assertEqual(self.sprint.completed_task_count, 1)
        self.assertIn("Completed 1 of 1 planned issues", self.sprint.close_summary)

    def test_closing_same_sprint_twice_is_idempotent(self):
        self.sprint.action_confirm_plan()
        self.sprint.action_start()
        self.task.state = "1_done"
        self.sprint.action_done()
        summary = self.sprint.close_summary
        self.sprint.action_done()
        self.assertEqual(self.sprint.state, "done")
        self.assertEqual(self.sprint.close_summary, summary)

    def test_start_rejects_scope_changed_since_confirmed_plan(self):
        self.sprint.action_confirm_plan()
        self.env["project.task"].create(
            {
                "name": "Late issue",
                "project_id": self.project.id,
                "sprint_id": self.sprint.id,
            }
        )
        with self.assertRaises(UserError):
            self.sprint.action_start()
        self.assertEqual(self.sprint.state, "draft")

    def test_estimate_is_optional_and_zero_is_distinct_from_unset(self):
        self.assertFalse(self.task.story_points_estimated)
        self.assertEqual(self.sprint.unestimated_issue_count, 1)
        self.task.write({"story_points": 0})
        self.assertTrue(self.task.story_points_estimated)
        self.assertEqual(self.sprint.unestimated_issue_count, 0)
        self.assertEqual(self.sprint.planned_points, 0)
        with self.assertRaises(ValidationError):
            self.task.write({"story_points": -0.5})

    def test_capacity_totals_split_shared_points_and_exclude_canceled_and_inactive(self):
        other_member = self._create_new_internal_user(
            login="scrum_second_member", groups="project.group_project_user"
        )
        self.sprint.user_ids = [(4, other_member.id)]
        self.task.write(
            {
                "story_points": 5,
                "user_ids": [(6, 0, [self.user_demo.id, other_member.id])],
            }
        )
        capacities = self.env["project.sprint.capacity"].create(
            [
                {"sprint_id": self.sprint.id, "user_id": self.user_demo.id, "capacity_points": 2},
                {"sprint_id": self.sprint.id, "user_id": other_member.id, "capacity_points": 2},
            ]
        )
        with self.assertRaises(ValidationError):
            self.env["project.sprint.capacity"].create(
                {
                    "sprint_id": self.sprint.id,
                    "user_id": self.user_demo.id,
                    "capacity_points": -1,
                }
            )
        self.assertEqual(self.sprint.planned_points, 5)
        self.assertEqual(sum(capacities.mapped("planned_points")), 5)
        self.assertTrue(all(capacities.mapped("over_capacity")))
        member_capacity = capacities.filtered(lambda line: line.user_id == self.user_demo)
        self.assertEqual(
            member_capacity.with_user(self.user_demo).read(["planned_points"])[0][
                "planned_points"
            ],
            2.5,
        )
        with self.assertRaises(UserError):
            member_capacity.with_user(self.user_demo).write({"capacity_points": 10})
        other_member.active = False
        self.assertEqual(capacities.filtered(lambda line: line.user_id == other_member).planned_points, 0)
        self.assertEqual(capacities.filtered(lambda line: line.user_id == self.user_demo).planned_points, 5)
        self.assertNotIn(other_member, self.sprint._active_capacity_members())
        self.task.state = "1_canceled"
        self.assertEqual(self.sprint.planned_points, 0)
        self.assertEqual(sum(capacities.mapped("planned_points")), 0)

    def test_started_commitment_keeps_estimate_snapshot_after_later_edit(self):
        self.task.write({"story_points": 3})
        self.sprint.action_confirm_plan()
        self.sprint.action_start()
        line = self.sprint.commitment_ids.line_ids
        self.task.write({"story_points": 8})
        self.assertEqual(line.story_points_snapshot, 3)
        self.assertEqual(self.sprint.planned_points, 3)

    def test_manager_can_correct_closed_sprint_with_immutable_reasoned_audit(self):
        self.sprint.action_confirm_plan()
        self.sprint.action_start()
        self.task.state = "1_done"
        self.sprint.action_done()
        correction_task = self.env["project.task"].create(
            {"name": "Correction issue", "project_id": self.project.id}
        )
        wizard = self.env["project.sprint.correction.wizard"].create(
            {
                "sprint_id": self.sprint.id,
                "operation": "add",
                "task_ids": [(6, 0, correction_task.ids)],
                "reason": "Issue was omitted from the completed sprint.",
            }
        )
        invalid_reason = self.env["project.sprint.correction.wizard"].create(
            {
                "sprint_id": self.sprint.id,
                "operation": "add",
                "task_ids": [(6, 0, correction_task.ids)],
                "reason": "   ",
            }
        )
        with self.assertRaises(ValidationError):
            invalid_reason.action_apply()
        self.assertFalse(self.sprint.correction_ids)
        wizard.action_apply()
        self.assertEqual(correction_task.sprint_id, self.sprint)
        self.assertEqual(len(self.sprint.correction_ids), 1)
        correction = self.sprint.correction_ids
        self.assertEqual(correction.reason, wizard.reason)
        self.assertEqual(correction.operation, "add")
        summary = self.sprint.close_summary
        removal = self.env["project.sprint.correction.wizard"].create(
            {
                "sprint_id": self.sprint.id,
                "operation": "remove",
                "task_ids": [(6, 0, correction_task.ids)],
                "reason": "The issue belongs in the backlog.",
            }
        )
        removal.action_apply()
        self.assertFalse(correction_task.sprint_id)
        self.assertEqual(len(self.sprint.correction_ids), 2)
        self.assertEqual(self.sprint.close_summary, summary)
        with self.assertRaises(UserError):
            self.sprint.unlink()
        self.assertEqual(len(self.sprint.correction_ids), 2)
        with self.assertRaises(UserError):
            correction.write({"reason": "Tampered"})
        with self.assertRaises(UserError):
            self.sprint.with_user(self.user_demo).action_open_correction()
        with self.assertRaises(UserError):
            removal.with_user(self.user_demo).action_apply()

    def test_project_user_cannot_start_sprint_even_after_plan_confirmation(self):
        self.sprint.action_confirm_plan()
        with self.assertRaises(UserError):
            self.sprint.with_user(self.user_demo).action_start()

    def test_project_user_can_read_but_not_manage_sprints(self):
        sprint_as_user = self.sprint.with_user(self.user_demo)
        self.assertEqual(sprint_as_user.search_count([("id", "=", self.sprint.id)]), 1)
        with self.assertRaises(UserError):
            sprint_as_user.write({"name": "Unauthorized edit"})
        with self.assertRaises(UserError):
            sprint_as_user.action_confirm_plan()
