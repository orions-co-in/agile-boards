from datetime import datetime, time, timedelta

from datetime import UTC
from zoneinfo import ZoneInfo

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, new_test_user


class TestAgileMetrics(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(
            cls.env, login="metrics_manager", groups="project.group_project_manager"
        )
        cls.contributor = new_test_user(
            cls.env, login="metrics_contributor", groups="project.group_project_user"
        )
        cls.reviewer = new_test_user(
            cls.env, login="metrics_reviewer", groups="agile_community.group_agile_reviewer"
        )
        cls.project = cls.env["project.project"].create({
            "name": "Metrics project",
            "privacy_visibility": "employees",
            "user_id": cls.manager.id,
            "agile_enabled": True,
            "agile_key": "METR",
            "allow_task_dependencies": True,
        })
        cls.outsider = new_test_user(
            cls.env,
            login="metrics_outsider",
            groups="project.group_project_user",
        )

    def _issue(self, name="Metrics issue", **extra):
        values = {
            "name": name,
            "project_id": self.project.id,
            "description": "A reportable software issue.",
            "user_ids": [(6, 0, [self.contributor.id])],
        }
        values.update(extra)
        return self.env["project.task"].with_user(self.manager).create(values)

    def _stage(self, status):
        return self.env["project.task.type"].with_context(active_test=False).search([
            ("project_ids", "=", self.project.id),
            ("agile_status", "=", status),
        ], limit=1)

    def test_project_overview_counts_leaf_issues_and_drills_down(self):
        issue = self._issue("Open and blocked", agile_blocked=True, agile_block_reason="Waiting for API")
        dependency = self._issue("Open dependency")
        dependency_waiting = self._issue("Waiting for dependency")
        dependency_waiting.write({"depend_on_ids": [(4, dependency.id)]})
        canceled = self._issue("Canceled issue")
        canceled.action_agile_cancel()
        self._issue("Overdue issue", date_deadline="2000-01-01 00:00:00")
        project = self.project.with_user(self.contributor)

        self.assertEqual(dependency_waiting.state, "04_waiting_normal")
        self.assertEqual(project.agile_open_issue_count, 4)
        self.assertEqual(project.agile_blocked_issue_count, 2)
        self.assertEqual(project.agile_overdue_issue_count, 1)
        action = project.with_context(agile_metric_filter="blocked").action_view_agile_metric_issues()
        self.assertIn(("agile_is_blocked", "=", True), action["domain"])
        self.assertEqual(
            self.env["project.task"].with_user(self.contributor).search(action["domain"]).ids,
            [issue.id, dependency_waiting.id],
        )
        report_action = project.action_view_agile_reports()
        self.assertEqual(report_action["context"]["graph_measure"], "remaining_points")

    def test_throughput_action_exposes_read_only_milestone_detail(self):
        action = self.env.ref("agile_community.agile_issue_metric_event_action")
        self.assertIn("form", action.view_mode.split(","))
        list_view = self.env.ref("agile_community.agile_issue_metric_event_list")
        self.assertIn("name=\"action_open_issue\"", list_view.arch_db)

    def test_agile_overview_and_drilldowns_require_project_membership(self):
        member_project = self.project.with_user(self.contributor)
        self.assertTrue(member_project.can_view_agile_metrics)
        self.assertEqual(
            member_project.action_view_agile_reports()["domain"],
            [("project_id", "=", self.project.id)],
        )

        outsider_project = self.project.with_user(self.outsider)
        self.assertFalse(outsider_project.can_view_agile_metrics)
        with self.assertRaises(AccessError):
            outsider_project.action_view_agile_metric_issues()
        with self.assertRaises(AccessError):
            outsider_project.action_view_agile_reports()
        with self.assertRaises(AccessError):
            outsider_project.action_view_agile_current_sprint()

    def test_revoked_project_access_does_not_expose_project_reports_or_releases(self):
        private_project = self.env["project.project"].with_user(self.manager).create({
            "name": "Follower-only Agile metrics",
            "privacy_visibility": "followers",
            "user_id": self.manager.id,
            "agile_enabled": True,
            "agile_key": "PRIVMET",
        })
        private_project.with_user(self.manager).write({
            "allowed_internal_user_ids": [Command.link(self.manager.id), Command.link(self.contributor.id)],
        })
        self.env["agile.project.member"].with_user(self.manager).create({
            "project_id": private_project.id,
            "user_id": self.contributor.id,
            "role": "contributor",
        })
        assigned_issue = self.env["project.task"].with_user(self.manager).create({
            "name": "Still natively assigned",
            "project_id": private_project.id,
            "user_ids": [(6, 0, [self.contributor.id])],
        })
        hidden_issue = self.env["project.task"].with_user(self.manager).create({
            "name": "No longer natively visible",
            "project_id": private_project.id,
        })
        release = self.env["project.version"].with_user(self.manager).create({
            "name": "Private release",
            "project_id": private_project.id,
        })
        sprint = self.env["project.sprint"].with_user(self.manager).create({
            "name": "Private sprint history",
            "project_id": private_project.id,
            "date_start": "2026-09-24",
            "date_option": "custom",
            "date_end": "2026-09-30",
        })
        snapshot = self.env["agile.metric.snapshot"].sudo().create({
            "snapshot_key": f"{private_project.id}:0:2026-09-26:daily",
            "project_id": private_project.id,
            "snapshot_date": "2026-09-26",
            "captured_at": "2026-09-26 00:00:00",
            "capture_kind": "daily",
        })
        lines = self.env["agile.metric.snapshot.line"].sudo().create([
            {
                "snapshot_id": snapshot.id,
                "project_id": private_project.id,
                "task_id": issue.id,
                "issue_key": issue.issue_key,
                "issue_name": issue.name,
                "status": "backlog",
                "issue_count": 1,
            }
            for issue in (assigned_issue, hidden_issue)
        ])

        private_project.with_user(self.manager).write({"allowed_internal_user_ids": [Command.unlink(self.contributor.id)]})

        self.env.flush_all()
        self.env.invalidate_all()
        self.assertFalse(
            private_project.with_user(self.contributor).has_access("read")
        )
        self.assertTrue(assigned_issue.with_user(self.contributor).has_access("read"))
        with self.assertRaises(AccessError):
            assigned_issue.with_user(self.contributor).write({
                "name": "Mutation after Project access was revoked",
            })
        with self.assertRaises(AccessError):
            self.env["project.task"].with_user(self.contributor).create({
                "name": "Creation after Project access was revoked",
                "project_id": private_project.id,
            })
        with self.assertRaises(AccessError):
            private_project.with_user(self.contributor).action_view_agile_reports()
        self.assertFalse(
            self.env["project.version"].with_user(self.contributor).search([
                ("id", "=", release.id),
            ])
        )
        self.assertFalse(
            self.env["agile_community.release_audit"].with_user(
                self.contributor
            ).search([("release_id", "=", release.id)])
        )
        self.assertFalse(
            self.env["agile.metric.snapshot"].with_user(self.contributor).search([
                ("id", "=", snapshot.id),
            ])
        )
        self.assertFalse(
            self.env["project.sprint"].with_user(self.contributor).search([
                ("id", "=", sprint.id),
            ])
        )
        visible_lines = self.env["agile.metric.snapshot.line"].with_user(
            self.contributor
        ).search([("id", "in", lines.ids)])
        self.assertEqual(visible_lines.task_id, assigned_issue)

    def test_overdue_uses_viewer_local_start_of_day(self):
        timezone = "Asia/Kolkata"
        project = self.project.with_user(self.contributor).with_context(tz=timezone)
        today = fields.Date.context_today(project)
        utc_boundary = datetime.combine(today, time.min).replace(
            tzinfo=ZoneInfo(timezone)
        ).astimezone(UTC)
        before = utc_boundary - timedelta(minutes=1)
        after = utc_boundary + timedelta(minutes=1)
        self._issue("Yesterday deadline", date_deadline=fields.Datetime.to_string(before.replace(tzinfo=None)))
        self._issue("Today deadline", date_deadline=fields.Datetime.to_string(after.replace(tzinfo=None)))

        self.assertEqual(project.agile_overdue_issue_count, 1)

    def test_first_start_and_completion_history_is_immutable_and_distinct(self):
        task = self._issue("Cycle time issue", story_points=3)
        task.with_user(self.manager).action_agile_mark_ready()
        task.with_user(self.manager).action_agile_start()
        task.with_user(self.manager).action_agile_send_review()
        task.with_user(self.reviewer).action_agile_complete()

        events = self.env["agile.issue.metric.event"].sudo().search(
            [("task_id", "=", task.id)], order="event_type"
        )
        self.assertEqual(set(events.mapped("event_type")), {"started", "completed"})
        started = events.filtered(lambda event: event.event_type == "started")
        self.assertEqual(started.throughput_points, 0)
        completed = events.filtered(lambda event: event.event_type == "completed")
        self.assertEqual(completed.story_points, 3)
        self.assertEqual(completed.throughput_points, 3)
        self.assertGreaterEqual(completed.cycle_time_days, 0)
        issue_action = completed.with_user(self.reviewer).action_open_issue()
        self.assertEqual(issue_action["res_model"], "project.task")
        self.assertEqual(issue_action["res_id"], task.id)
        contributor_action = completed.with_user(self.contributor).action_open_issue()
        self.assertEqual(contributor_action["res_model"], "project.task")
        self.assertEqual(contributor_action["res_id"], task.id)

        task.with_user(self.manager).action_agile_reopen()
        task.with_user(self.manager).action_agile_send_review()
        task.with_user(self.reviewer).action_agile_complete()
        self.assertEqual(
            self.env["agile.issue.metric.event"].sudo().search_count(
                [("task_id", "=", task.id)]
            ),
            2,
        )
        with self.assertRaises(UserError):
            completed.write({"cycle_time_days": 100})

    def test_cycle_time_uses_elapsed_calendar_days_and_canceled_work_has_no_throughput(self):
        task = self._issue("Timed cycle", story_points=8)
        metrics = self.env["agile.issue.metric.event"].sudo()
        started_at = datetime(2026, 9, 24, 9, 0, 0)
        completed_at = datetime(2026, 9, 24, 15, 0, 0)
        metrics._record_first_transition(task, "started", started_at)
        completion = metrics._record_first_transition(task, "completed", completed_at)
        self.assertEqual(completion.cycle_time_days, 0.25)
        self.assertEqual(completion.throughput_points, 8)

        canceled = self._issue("Canceled throughput", story_points=13)
        canceled.with_user(self.manager).action_agile_cancel()
        self.assertFalse(metrics.search([("task_id", "=", canceled.id)]))

    def test_empty_flow_pivot_does_not_render_sample_metrics(self):
        view = self.env.ref("agile_community.agile_metric_snapshot_line_pivot")
        self.assertNotIn('sample="1"', view.arch_db)

    def test_daily_snapshot_is_idempotent_read_only_and_keeps_each_days_value(self):
        task = self._issue("Snapshot issue", story_points=5)
        metric_model = self.env["agile.metric.snapshot"].sudo()
        day_one = datetime(2026, 9, 24, 23, 0, 0)
        first = metric_model._capture_project(self.project, captured_at=day_one)
        repeated = metric_model._capture_project(self.project, captured_at=day_one)
        self.assertEqual(first, repeated)
        line = first.line_ids.filtered(lambda row: row.task_id == task)
        self.assertEqual(line.story_points, 5)
        self.assertEqual(line.remaining_points, 5)

        task.with_user(self.manager).write({"story_points": 8})
        next_day = metric_model._capture_project(
            self.project, captured_at=datetime(2026, 9, 25, 23, 0, 0)
        )
        next_line = next_day.line_ids.filtered(lambda row: row.task_id == task)
        self.assertEqual(next_line.story_points, 8)
        self.assertEqual(line.story_points, 5)
        with self.assertRaises(UserError):
            self.env["agile.metric.snapshot"].with_user(self.contributor).with_context(
                allow_agile_metric_snapshot_write=True
            ).create({
                "snapshot_key": "forged",
                "project_id": self.project.id,
                "snapshot_date": "2026-09-26",
                "captured_at": "2026-09-26 00:00:00",
                "capture_kind": "daily",
            })

    def test_daily_snapshot_marks_dependency_waiting_as_blocked(self):
        dependency = self._issue("Snapshot dependency")
        waiting = self._issue("Snapshot waiting issue")
        waiting.write({"depend_on_ids": [(4, dependency.id)]})
        snapshot = self.env["agile.metric.snapshot"].sudo()._capture_project(
            self.project,
            captured_at=datetime(2026, 9, 26, 12),
        )
        line = snapshot.line_ids.filtered(lambda row: row.task_id == waiting)
        self.assertEqual(waiting.state, "04_waiting_normal")
        self.assertTrue(line.is_blocked)

    def test_sprint_snapshot_marks_scope_delta_and_honors_task_visibility(self):
        private_project = self.env["project.project"].create({
            "name": "Private metrics",
            "privacy_visibility": "followers",
            "user_id": self.manager.id,
            "agile_enabled": True,
            "agile_key": "MPRV",
        })
        private_issue = self.env["project.task"].with_user(self.manager).create({
            "name": "Assigned private issue",
            "project_id": private_project.id,
            "description": "Visible to the assignee, not all Project users.",
            "user_ids": [(6, 0, [self.contributor.id])],
            "story_points": 2,
        })
        sprint = self.env["project.sprint"].with_user(self.manager).create({
            "name": "Metrics sprint",
            "project_id": private_project.id,
            "date_start": "2026-09-24",
            "date_option": "custom",
            "date_end": "2026-09-30",
        })
        metric_model = self.env["agile.metric.snapshot"].sudo()
        first = metric_model._capture_sprint(
            sprint, capture_kind="started", captured_at=datetime(2026, 9, 24, 9)
        )
        self.assertEqual(first.scope_change_count, 0)
        private_issue.with_user(self.manager).write({"sprint_id": sprint.id})
        second = metric_model._capture_sprint(
            sprint, captured_at=datetime(2026, 9, 25, 9)
        )
        self.assertEqual(second.scope_change_count, 1)

        lines = self.env["agile.metric.snapshot.line"].with_user(self.contributor)
        # Assignment grants native task visibility, but not Agile reporting
        # access when the private Project itself is not visible to the user.
        self.assertEqual(lines.search_count([("task_id", "=", private_issue.id)]), 0)
        self.assertFalse(
            lines.with_user(self.reviewer).search_count([("task_id", "=", private_issue.id)])
        )

    def test_native_project_has_no_agile_overview_metrics(self):
        project = self.env["project.project"].create({"name": "Native project"})
        self.assertFalse(project.agile_enabled)
        self.assertEqual(project.agile_open_issue_count, 0)
        self.assertFalse(project.agile_current_sprint_id)
