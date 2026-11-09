from datetime import date, datetime, time, timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, new_test_user

from odoo.addons.agile_community.models.agile_pulse import (
    METRIC_FILTERS,
    build_pulse_days,
    pace_for,
)


class TestPulseDays(TransactionCase):
    """Pure day-strip maths: ideal line, carry-forward, scope, long sprints."""

    # Monday 2026-10-05 to Friday 2026-10-16: ten working days, one weekend.
    START = date(2026, 10, 5)
    END = date(2026, 10, 16)

    def test_ideal_falls_from_committed_to_zero_and_is_flat_over_weekend(self):
        days = build_pulse_days(self.START, self.END, date(2026, 10, 7), 18.0, {})
        ideal = {d["date"]: d["ideal_left"] for d in days}
        self.assertEqual(ideal["2026-10-05"], 18.0)
        self.assertEqual(ideal["2026-10-16"], 0.0)
        self.assertEqual(ideal["2026-10-10"], ideal["2026-10-09"])
        self.assertEqual(ideal["2026-10-11"], ideal["2026-10-09"])
        self.assertEqual(len(days), 12)
        self.assertEqual([d["is_weekend"] for d in days].count(True), 2)

    def test_future_days_have_no_points_and_missing_past_days_carry_forward(self):
        snaps = {date(2026, 10, 5): (18.0, 18.0, False), date(2026, 10, 7): (12.0, 18.0, False)}
        days = {d["date"]: d for d in build_pulse_days(self.START, self.END, date(2026, 10, 8), 18.0, snaps)}
        self.assertEqual(days["2026-10-06"]["points_left"], 18.0)
        self.assertTrue(days["2026-10-06"]["estimated"])
        self.assertEqual(days["2026-10-07"]["points_left"], 12.0)
        self.assertFalse(days["2026-10-07"]["estimated"])
        self.assertEqual(days["2026-10-08"]["points_left"], 12.0)
        self.assertTrue(days["2026-10-08"]["is_today"])
        self.assertIsNone(days["2026-10-09"]["points_left"])
        self.assertTrue(days["2026-10-09"]["is_future"])

    def test_scope_change_reports_point_delta_against_previous_snapshot(self):
        snaps = {
            date(2026, 10, 5): (18.0, 18.0, False),
            date(2026, 10, 6): (17.0, 18.0, False),
            date(2026, 10, 7): (19.0, 21.0, True),
        }
        days = {d["date"]: d for d in build_pulse_days(self.START, self.END, date(2026, 10, 7), 18.0, snaps)}
        self.assertTrue(days["2026-10-07"]["scope_changed"])
        self.assertEqual(days["2026-10-07"]["scope_points"], 3.0)
        self.assertFalse(days["2026-10-06"]["scope_changed"])

    def test_first_snapshot_never_counts_as_scope_change(self):
        snaps = {date(2026, 10, 5): (18.0, 18.0, True)}
        days = build_pulse_days(self.START, self.END, date(2026, 10, 5), 18.0, snaps)
        self.assertFalse(days[0]["scope_changed"])

    def test_long_sprint_shows_a_21_day_window_containing_today(self):
        start, end = date(2026, 10, 1), date(2026, 12, 31)
        for today in (date(2026, 10, 1), date(2026, 11, 15), date(2026, 12, 31)):
            days = build_pulse_days(start, end, today, 40.0, {})
            self.assertEqual(len(days), 21, today)
            self.assertIn(today.isoformat(), [d["date"] for d in days])
            self.assertEqual(days[0]["day_number"], (date.fromisoformat(days[0]["date"]) - start).days + 1)

    def test_single_day_sprint_and_weekend_only_sprint_do_not_divide_by_zero(self):
        one = build_pulse_days(date(2026, 10, 5), date(2026, 10, 5), date(2026, 10, 5), 5.0, {})
        self.assertEqual(one[0]["ideal_left"], 5.0)
        weekend = build_pulse_days(date(2026, 10, 10), date(2026, 10, 11), date(2026, 10, 10), 5.0, {})
        self.assertEqual([d["ideal_left"] for d in weekend], [5.0, 5.0])

    def test_pace_wording_thresholds(self):
        self.assertEqual(pace_for(16.0, 9.0)["status"], "behind")
        self.assertEqual(pace_for(16.0, 9.0)["delta"], 7.0)
        self.assertEqual(pace_for(8.0, 9.0)["status"], "on_pace")
        self.assertEqual(pace_for(10.0, 9.0)["status"], "on_pace")
        self.assertEqual(pace_for(5.0, 9.0)["status"], "ahead")
        self.assertIsNone(pace_for(None, 9.0))


class TestAgilePulseData(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(
            cls.env, login="pulse_manager", groups="project.group_project_manager"
        )
        cls.contributor = new_test_user(
            cls.env, login="pulse_contributor", groups="project.group_project_user"
        )
        cls.project = cls.env["project.project"].with_user(cls.manager).create({
            "name": "Pulse project",
            "privacy_visibility": "employees",
            "agile_enabled": True,
            "agile_key": "PULS",
            "agile_method": "scrum",
        })
        cls.outsider = new_test_user(
            cls.env, login="pulse_outsider", groups="project.group_project_user"
        )
        cls.today = fields.Date.context_today(cls.project)

    def _issue(self, name, points=3, **extra):
        values = {
            "name": name,
            "project_id": self.project.id,
            "description": "Pulse issue.",
            "story_points": points,
        }
        values.update(extra)
        return self.env["project.task"].with_user(self.manager).create(values)

    def _sprint(self, start_offset=-3, length=7, **extra):
        start = self.today + timedelta(days=start_offset)
        values = {
            "name": "Pulse sprint",
            "project_id": self.project.id,
            "date_start": start,
            "date_option": "custom",
            "date_end": start + timedelta(days=length - 1),
        }
        values.update(extra)
        return self.env["project.sprint"].with_user(self.manager).create(values)

    def _finish(self, issue):
        issue = issue.with_user(self.manager)
        for step in ("mark_ready", "start", "send_review", "complete"):
            getattr(issue, f"action_agile_{step}")()

    def _start(self, sprint):
        sprint.action_confirm_plan()
        sprint.action_start()

    def _data(self, user=None):
        return self.project.with_user(user or self.manager).agile_pulse_data()

    def test_kanban_project_returns_counts_only(self):
        self.project.with_user(self.manager).write({"agile_method": "kanban"})
        self._issue("Kanban issue")
        data = self._data()
        self.assertEqual(data["state"], "kanban")
        self.assertEqual(data["counts"]["open"], 1)
        self.assertEqual(data["days"], [])

    def test_scrum_project_without_sprints_is_none(self):
        self.assertEqual(self._data()["state"], "none")

    def test_planned_sprint_reports_points_and_capacity(self):
        sprint = self._sprint(start_offset=2)
        self._issue("Planned", points=5).write({"sprint_id": sprint.id})
        data = self._data()
        self.assertEqual(data["state"], "planned")
        self.assertEqual(data["sprint"]["planned_points"], 5.0)
        self.assertEqual(data["sprint"]["name"], "Pulse sprint")
        self.assertTrue(data["can_manage"])
        self.assertFalse(self._data(self.contributor_member())["can_manage"])

    def contributor_member(self):
        existing = self.env["agile.project.member"].search([
            ("project_id", "=", self.project.id), ("user_id", "=", self.contributor.id),
        ])
        if not existing:
            self.env["agile.project.member"].with_user(self.manager).create({
                "project_id": self.project.id,
                "user_id": self.contributor.id,
                "role": "contributor",
            })
        return self.contributor

    def test_active_sprint_builds_days_pace_and_scope_changes(self):
        sprint = self._sprint(start_offset=-3)
        first = self._issue("First", points=5)
        second = self._issue("Second", points=3)
        first.write({"sprint_id": sprint.id})
        second.write({"sprint_id": sprint.id})
        self._start(sprint)
        metric = self.env["agile.metric.snapshot"].sudo()
        day = lambda offset: datetime.combine(self.today + timedelta(days=offset), time(9))
        metric._capture_sprint(sprint, capture_kind="daily", captured_at=day(-3))
        metric._capture_sprint(sprint, capture_kind="daily", captured_at=day(-2))
        added = self._issue("Added late", points=2)
        added.write({"sprint_id": sprint.id})
        metric._capture_sprint(sprint, capture_kind="daily", captured_at=day(-1))
        metric._capture_sprint(
            sprint, capture_kind="daily", captured_at=fields.Datetime.now() + timedelta(seconds=1)
        )

        data = self._data()
        self.assertEqual(data["state"], "active")
        self.assertEqual(data["sprint"]["total_days"], 7)
        today_cell = next(d for d in data["days"] if d["is_today"])
        self.assertEqual(today_cell["points_left"], 10.0)
        self.assertEqual(data["pace"]["points_left"], 10.0)
        self.assertIn(data["pace"]["status"], ("behind", "ahead", "on_pace"))
        self.assertEqual(
            [c["points_delta"] for c in data["scope_changes"]], [2.0]
        )
        self.assertTrue(all(d["points_left"] is None for d in data["days"] if d["is_future"]))

    def test_done_issue_lowers_points_left(self):
        sprint = self._sprint(start_offset=-1)
        done = self._issue("Done one", points=5)
        open_ = self._issue("Open one", points=3)
        done.write({"sprint_id": sprint.id})
        open_.write({"sprint_id": sprint.id})
        self._start(sprint)
        self._finish(done)
        self.env["agile.metric.snapshot"].sudo()._capture_sprint(
            sprint, capture_kind="daily", captured_at=fields.Datetime.now() + timedelta(seconds=1)
        )
        today_cell = next(d for d in self._data()["days"] if d["is_today"])
        self.assertEqual(today_cell["points_left"], 3.0)

    def test_issue_finished_after_the_last_snapshot_counts_today(self):
        # NU-02: no new snapshot is captured after the work is done.
        sprint = self._sprint(start_offset=0)
        done = self._issue("Done today", points=5)
        open_ = self._issue("Open today", points=3)
        done.write({"sprint_id": sprint.id})
        open_.write({"sprint_id": sprint.id})
        self._start(sprint)
        self.env["agile.metric.snapshot"].sudo()._capture_sprint(sprint, capture_kind="daily")
        self._finish(done)
        data = self._data()
        today_cell = next(d for d in data["days"] if d["is_today"])
        self.assertEqual(today_cell["points_left"], 3.0)
        self.assertEqual(data["pace"]["points_left"], 3.0)
        self.assertEqual(data["scope_changes"], [])

    def test_active_sprint_with_no_snapshot_waits(self):
        sprint = self._sprint(start_offset=0)
        self._issue("Waiting", points=2).write({"sprint_id": sprint.id})
        self._start(sprint)
        self.env.cr.execute("DELETE FROM agile_metric_snapshot_line")
        self.env.cr.execute("DELETE FROM agile_metric_snapshot")
        self.env.invalidate_all()
        data = self._data()
        self.assertEqual(data["state"], "waiting")
        self.assertEqual(data["days"], [])

    def test_completed_sprint_shows_final_values(self):
        sprint = self._sprint(start_offset=-6)
        finished = self._issue("Finished", points=4)
        finished.write({"sprint_id": sprint.id})
        self._start(sprint)
        self._finish(finished)
        sprint.action_done()
        data = self._data()
        self.assertEqual(data["state"], "completed")
        self.assertIsNone(data["pace"])
        self.assertEqual(data["sprint"]["state"], "done")
        self.assertTrue(data["days"])

    def test_counts_match_the_drill_down_lists_for_the_same_user(self):
        self._issue("Open")
        self._issue("Blocked", agile_blocked=True, agile_block_reason="Waiting")
        self._issue("Overdue", date_deadline="2000-01-01 00:00:00")
        review = self._issue("Review")
        for step in ("mark_ready", "start", "send_review"):
            getattr(review.with_user(self.manager), f"action_agile_{step}")()
        member = self.contributor_member()
        counts = self._data(member)["counts"]
        project = self.project.with_user(member)
        for metric in METRIC_FILTERS:
            action = project.with_context(agile_metric_filter=metric).action_view_agile_metric_issues()
            found = self.env["project.task"].with_user(member).search_count(action["domain"])
            self.assertEqual(counts[metric], found, metric)
        self.assertEqual(counts["review"], 1)
        self.assertEqual(counts["blocked"], 1)
        self.assertGreaterEqual(counts["open"], 4)

    def test_non_members_and_native_projects_are_refused(self):
        with self.assertRaises(AccessError):
            self._data(self.outsider)
        native = self.env["project.project"].create({"name": "Native"})
        with self.assertRaises(UserError):
            native.with_user(self.manager).agile_pulse_data()

    def test_overview_action_targets_the_client_action_for_members_only(self):
        action = self.project.with_user(self.manager).action_open_agile_overview()
        self.assertEqual(action["tag"], "agile_community.overview")
        self.assertEqual(action["params"], {"project_id": self.project.id})
        with self.assertRaises(AccessError):
            self.project.with_user(self.outsider).action_open_agile_overview()
