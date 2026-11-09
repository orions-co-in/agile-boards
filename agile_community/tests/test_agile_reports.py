from datetime import datetime, time, timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, new_test_user


class AgileReportCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, login="rep_manager", groups="project.group_project_manager")
        cls.outsider = new_test_user(cls.env, login="rep_outsider", groups="project.group_project_user")
        cls.project = cls.env["project.project"].with_user(cls.manager).create({
            "name": "Report project", "privacy_visibility": "employees", "agile_enabled": True,
            "agile_key": "REP", "agile_method": "scrum",
        })
        cls.env["agile.project.member"].sudo().search([
            ("project_id", "=", cls.project.id), ("user_id", "=", cls.outsider.id)]).unlink()
        cls.today = fields.Date.context_today(cls.project)
        cls.Report = cls.env["agile.report"].with_user(cls.manager)

    def _issue(self, name, points):
        return self.env["project.task"].with_user(self.manager).create({
            "name": name, "project_id": self.project.id, "description": "Report issue.", "story_points": points,
        })

    def _sprint(self, start_offset=-6):
        start = self.today + timedelta(days=start_offset)
        return self.env["project.sprint"].with_user(self.manager).create({
            "name": "Report sprint", "project_id": self.project.id, "date_start": start,
            "date_option": "custom", "date_end": start + timedelta(days=6),
        })

    def _finish(self, issue):
        for step in ("mark_ready", "start", "send_review", "complete"):
            getattr(issue.with_user(self.manager), f"action_agile_{step}")()

    def _backdate_leaving(self, issue, sprint):
        """C was taken out two days before the sprint closed."""
        self.env.cr.precommit.run()  # tracking is written when the transaction commits
        self.env.flush_all()
        self.env.cr.execute(
            """UPDATE mail_tracking_value v SET create_date = v.create_date - interval '2 days'
               FROM mail_message m, ir_model_fields f
               WHERE v.mail_message_id = m.id AND m.model = 'project.task' AND m.res_id = %s
                 AND v.field_id = f.id AND f.name = 'sprint_id' AND v.old_value_integer = %s""",
            (issue.id, sprint.id))
        self.env["mail.tracking.value"].invalidate_model()

    def _group(self, data, code):
        return data["groups"][code]

    def _scenario(self):
        """A done, B unfinished and moved out when closing, C removed two days before the close, D added after the start and done."""
        sprint = self._sprint()
        a, b, c = self._issue("A", 5), self._issue("B", 3), self._issue("C", 2)
        for issue in (a, b, c):
            issue.write({"sprint_id": sprint.id})
        sprint.action_confirm_plan()
        sprint.action_start()
        d = self._issue("D", 4)
        d.write({"sprint_id": sprint.id})
        c.write({"sprint_id": False})
        self._backdate_leaving(c, sprint)
        self._finish(a)
        self._finish(d)
        b.write({"sprint_id": False})
        self.env.cr.precommit.run()
        sprint.action_done()
        return sprint, a, b, c, d

    def _snapshot(self, offset):
        when = fields.Datetime.now().replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=offset)
        self.env["agile.metric.snapshot"].sudo()._capture_project(self.project, captured_at=when)
        return fields.Date.to_string(self.today + timedelta(days=offset))


class TestAgileSprintReport(AgileReportCase):
    def test_a_closed_sprint_report_counts_each_kind_of_change(self):
        sprint, a, b, c, d = self._scenario()
        data = self.Report.sprint_report(self.project.id, sprint.id)
        self.assertFalse(data["so_far"])
        self.assertEqual({k: v["count"] for k, v in data["groups"].items()},
                         {"planned": 3, "completed": 2, "carried": 1, "added": 1, "removed": 1})
        self.assertEqual(self._group(data, "planned")["points"], 10.0)
        self.assertEqual(self._group(data, "completed")["points"], 9.0)
        self.assertEqual(self._group(data, "added")["points"], 4.0)
        self.assertEqual(self._group(data, "removed")["points"], 2.0)
        self.assertEqual(self._group(data, "carried")["issues"][0]["name"], "B")
        self.assertEqual(self._group(data, "carried")["issues"][0]["where"], "Backlog")
        self.assertEqual(sorted(i["name"] for i in self._group(data, "completed")["issues"]), ["A", "D"])
        self.assertEqual(data["delivered"]["planned_points"], 10.0)
        self.assertEqual(data["delivered"]["percent"], 90)

    def test_the_figures_do_not_change_when_issues_move_later(self):
        sprint, a, b, c, d = self._scenario()
        before = self.Report.sprint_report(self.project.id, sprint.id)["groups"]
        b.write({"story_points": 13})  # a later estimate change
        later = self.env["project.sprint"].with_user(self.manager).create({
            "name": "Next", "project_id": self.project.id, "date_start": self.today + timedelta(days=2),
            "date_option": "custom", "date_end": self.today + timedelta(days=8)})
        b.write({"sprint_id": later.id})
        self.env.cr.precommit.run()
        after = self.Report.sprint_report(self.project.id, sprint.id)["groups"]
        for code in ("planned", "completed", "added", "removed"):
            self.assertEqual(before[code]["count"], after[code]["count"], code)
            self.assertEqual(before[code]["points"], after[code]["points"], code)
        self.assertEqual(after["carried"]["issues"][0]["where"], "Next", "carried over says where it went")

    def test_an_active_sprint_reports_progress_so_far(self):
        sprint = self._sprint(start_offset=-2)
        a, b = self._issue("A", 5), self._issue("B", 3)
        for issue in (a, b):
            issue.write({"sprint_id": sprint.id})
        sprint.action_confirm_plan()
        sprint.action_start()
        self._finish(a)
        data = self.Report.sprint_report(self.project.id, sprint.id)
        self.assertTrue(data["so_far"])
        self.assertEqual(self._group(data, "completed")["count"], 1)
        self.assertEqual([i["name"] for i in self._group(data, "carried")["issues"]], ["B"], "still open")
        self.assertEqual(data["delivered"]["percent"], 62)

    def test_a_sprint_without_a_plan_says_so_and_does_not_divide_by_zero(self):
        sprint = self._sprint()
        data = self.Report.sprint_report(self.project.id, sprint.id)
        self.assertTrue(data["no_plan"])
        self.assertIsNone(data["delivered"]["percent"])

    def test_drill_down_opens_the_issues_behind_a_tile(self):
        sprint, a, b, c, d = self._scenario()
        action = self.Report.sprint_report_issues(self.project.id, sprint.id, "completed")
        self.assertEqual(action["name"], "Report sprint: completed")
        found = self.env["project.task"].with_user(self.manager).search(action["domain"])
        self.assertEqual(found, a | d)
        self.assertNotIn("search_default_agile_hide_completed", action["context"])
        with self.assertRaises(UserError):
            self.Report.sprint_report_issues(self.project.id, sprint.id, "nonsense")

    def test_kanban_project_has_no_sprint_reports(self):
        """A Kanban project lists only the reports that make sense without sprints (NU-49)."""
        kanban = self.env["project.project"].with_user(self.manager).create({
            "name": "Kanban reports", "agile_enabled": True, "agile_key": "KNR", "agile_method": "kanban"})
        codes = [r["code"] for r in self.Report.reports_meta(kanban.id)["reports"]]
        for gone in ("sprint", "burnup", "velocity", "burndown"):
            self.assertNotIn(gone, codes)
        self.assertEqual(codes[0], "cfd")

    def test_access_and_hidden_issues(self):
        sprint, a, b, c, d = self._scenario()
        with self.assertRaises(AccessError):
            self.env["agile.report"].with_user(self.outsider).sprint_report(self.project.id, sprint.id)
        other = self.env["project.project"].with_user(self.manager).create({
            "name": "Other", "agile_enabled": True, "agile_key": "OTR"})
        with self.assertRaises(UserError):
            self.Report.sprint_report(other.id, sprint.id)
        meta = self.Report.reports_meta(self.project.id)
        self.assertEqual(meta["sprints"][0]["id"], sprint.id)
        self.assertEqual(meta["reports"][0]["code"], "sprint")
        # An issue the viewer cannot read is counted, not listed.
        reader = new_test_user(self.env, login="rep_reader", groups="project.group_project_user")
        self.env["agile.project.member"].sudo().create({
            "project_id": self.project.id, "user_id": reader.id, "role": "reviewer"}) if not self.env[
            "agile.project.member"].sudo().search([("project_id", "=", self.project.id), ("user_id", "=", reader.id)]) else None
        completed = self.env["agile.report"].with_user(reader).sprint_report(self.project.id, sprint.id)["groups"]["completed"]
        self.assertEqual(completed["count"], completed["hidden"] + len(completed["issues"]))


class TestAgileCumulativeFlow(AgileReportCase):
    def test_bands_count_issues_per_status_per_day(self):
        a, b, c = self._issue("A", 1), self._issue("B", 2), self._issue("C", 3)
        day1 = self._snapshot(-2)
        a.sudo()._agile_transition("ready")
        day2 = self._snapshot(-1)
        for step in ("progress", "review", "done"):
            a.sudo()._agile_transition(step)
        b.sudo()._agile_transition("ready")
        day3 = self._snapshot(0)
        data = self.Report.cfd(self.project.id, day1, day3)
        self.assertEqual([d["date"] for d in data["days"]], [day1, day2, day3])
        counts = [d["counts"] for d in data["days"]]
        self.assertEqual(counts[0]["backlog"], 3)
        self.assertEqual((counts[1]["backlog"], counts[1]["ready"]), (2, 1))
        self.assertEqual((counts[2]["done"], counts[2]["ready"], counts[2]["backlog"]), (1, 1, 1))
        self.assertTrue(all(d["total"] == 3 for d in data["days"]), "the bands add up to the issues")
        self.assertEqual([s["code"] for s in data["statuses"]], ["done", "review", "progress", "ready", "backlog"])

    def test_range_and_empty_and_limits(self):
        self._issue("A", 1)
        day = self._snapshot(-5)
        self.assertEqual(self.Report.cfd(self.project.id, day, day)["days"][0]["date"], day)
        self.assertEqual(self.Report.cfd(self.project.id, "2020-01-01", "2020-01-31")["days"], [])
        default = self.Report.cfd(self.project.id)
        self.assertEqual(default["to"], fields.Date.to_string(self.today))
        with self.assertRaises(UserError):
            self.Report.cfd(self.project.id, "2026-02-01", "2026-01-01")
        with self.assertRaises(UserError):
            self.Report.cfd(self.project.id, "2020-01-01", "2026-01-01")
        with self.assertRaises(AccessError):
            self.env["agile.report"].with_user(self.outsider).cfd(self.project.id)

    def test_drill_down_lists_the_issues_that_were_in_a_status_that_day(self):
        a, b = self._issue("A", 1), self._issue("B", 2)
        a.sudo()._agile_transition("ready")
        day = self._snapshot(-1)
        a.sudo()._agile_transition("progress")  # moved on afterwards
        action = self.Report.cfd_issues(self.project.id, day, "ready")
        self.assertEqual(self.env["project.task"].search(action["domain"]), a, "A was Ready that day")
        self.assertIn("To Do on", action["name"])
        with self.assertRaises(UserError):
            self.Report.cfd_issues(self.project.id, day, "nonsense")
        meta = self.Report.reports_meta(self.project.id)
        self.assertEqual(
            [r["code"] for r in meta["reports"] if not r.get("native")],
            ["sprint", "burnup", "cfd", "control"] + (["deploys"] if "agile.deployment" in self.env else []) + ["epic", "release"],
        )


class TestAgileBurndown(AgileReportCase):
    def _epic_with_children(self):
        epic_type = self.env.ref("agile_community.agile_task_type_epic")
        epic = self.env["project.task"].with_user(self.manager).create({
            "name": "Big epic", "project_id": self.project.id, "agile_task_type_id": epic_type.id})
        a, b = self._issue("A", 5), self._issue("B", 3)
        for issue in (a, b):
            issue.write({"parent_id": epic.id})
        return epic, a, b

    def test_epic_burndown_follows_remaining_points_and_scope_steps(self):
        epic, a, b = self._epic_with_children()
        day1 = self._snapshot(-2)
        for step in ("ready", "progress", "review", "done"):
            a.sudo()._agile_transition(step)
        late = self._issue("Late", 2)
        late.write({"parent_id": epic.id})
        day2 = self._snapshot(-1)
        b.sudo()._agile_transition("ready")
        day3 = self._snapshot(0)
        data = self.Report.burndown(self.project.id, "epic", epic.id, day1, day3)
        self.assertEqual([d["date"] for d in data["days"]], [day1, day2, day3])
        self.assertEqual([(d["scope"], d["remaining"]) for d in data["days"]], [(8.0, 8.0), (10.0, 5.0), (10.0, 5.0)])
        self.assertEqual(data["days"][1]["done"], 5.0)
        self.assertEqual(data["issue_count"], 3)

    def test_canceled_and_unestimated_issues_stay_out_of_the_points(self):
        epic, a, b = self._epic_with_children()
        extra = self._issue("No estimate", 0)
        extra.write({"parent_id": epic.id, "story_points": 0})
        b.sudo().action_agile_cancel()
        day = self._snapshot(0)
        data = self.Report.burndown(self.project.id, "epic", epic.id, day, day)
        self.assertEqual((data["days"][0]["scope"], data["days"][0]["remaining"]), (5.0, 5.0), "B is canceled")

    def test_release_burndown_uses_the_releases_issues(self):
        release = self.env["project.version"].with_user(self.manager).create({
            "name": "R1", "project_id": self.project.id})
        a, b = self._issue("A", 4), self._issue("B", 6)
        a.write({"version_id": release.id})
        day = self._snapshot(0)
        data = self.Report.burndown(self.project.id, "release", release.id, day, day)
        self.assertEqual(data["days"][0]["scope"], 4.0)
        meta = self.Report.reports_meta(self.project.id)
        self.assertEqual([r["code"] for r in meta["reports"]][-2:], ["epic", "release"])
        self.assertEqual(meta["releases"][0]["name"], "R1")

    def test_deep_link_opens_the_reports_page_on_one_report(self):
        sprint = self._sprint()
        action = self.Report.report_action(self.project.id, "sprint", sprint.id)
        self.assertEqual(action["tag"], "agile_community.reports")
        self.assertEqual(
            action["params"], {"project_id": self.project.id, "report": "sprint", "sprint_id": sprint.id}
        )
        self.assertEqual(action["context"]["active_id"], self.project.id)
        epic = self._epic_with_children()[0]
        self.assertEqual(self.Report.report_action(self.project.id, "epic", epic.id)["params"]["target_id"], epic.id)
        with self.assertRaises(UserError):
            self.Report.report_action(self.project.id, "velocity", 1)
        with self.assertRaises(AccessError):
            self.env["agile.report"].with_user(self.outsider).report_action(self.project.id, "sprint", sprint.id)

    def test_release_button_opens_its_burndown_as_a_plain_manager(self):
        release = self.env["project.version"].with_user(self.manager).create({
            "name": "R2", "project_id": self.project.id})
        action = release.with_user(self.manager).action_open_release_burndown()
        self.assertEqual(action["params"]["report"], "release")
        self.assertEqual(action["params"]["target_id"], release.id)

    def test_drill_down_access_and_wrong_targets(self):
        epic, a, b = self._epic_with_children()
        day = self._snapshot(0)
        a.sudo()._agile_transition("ready")
        action = self.Report.burndown_issues(self.project.id, "epic", epic.id, day)
        self.assertEqual(self.env["project.task"].search(action["domain"]), a | b)
        with self.assertRaises(UserError):
            self.Report.burndown(self.project.id, "epic", a.id, day, day)  # not an epic
        with self.assertRaises(UserError):
            self.Report.burndown(self.project.id, "release", 0, day, day)
        with self.assertRaises(UserError):
            self.Report.burndown(self.project.id, "sprint", epic.id, day, day)
        with self.assertRaises(AccessError):
            self.env["agile.report"].with_user(self.outsider).burndown(self.project.id, "epic", epic.id)


class TestSprintBurnup(AgileReportCase):
    """M-1052: points done per day against the sprint scope."""

    def _capture(self, sprint, offset):
        when = datetime.combine(self.today + timedelta(days=offset), time(9))
        self.env["agile.metric.snapshot"].sudo()._capture_sprint(sprint, capture_kind="daily", captured_at=when)

    def test_done_and_scope_per_day_and_a_scope_step(self):
        sprint = self._sprint(start_offset=-3)
        a, b = self._issue("A", 5), self._issue("B", 3)
        for issue in (a, b):
            issue.write({"sprint_id": sprint.id})
        sprint.action_confirm_plan()
        sprint.action_start()
        self._capture(sprint, -3)
        self._finish(a)
        self._capture(sprint, -2)
        late = self._issue("Late", 2)
        late.write({"sprint_id": sprint.id})
        self._capture(sprint, -1)
        data = self.Report.burnup(self.project.id, sprint.id)
        self.assertEqual(data["estimate_unit"], "points")
        # Starting the sprint also took a snapshot today; the three backdated days are the ones to read.
        days = data["days"][:3]
        self.assertEqual([(d["done"], d["scope"]) for d in days], [(0, 8), (5, 8), (5, 10)])
        self.assertEqual([d["remaining"] for d in days], [8, 3, 5])

    def test_a_sprint_without_snapshots_has_no_days(self):
        sprint = self._sprint()
        self.assertEqual(self.Report.burnup(self.project.id, sprint.id)["days"], [])

    def test_access_and_wrong_sprint(self):
        sprint = self._sprint()
        with self.assertRaises(UserError):
            self.Report.burnup(self.project.id, 0)
        with self.assertRaises(AccessError):
            self.env["agile.report"].with_user(self.outsider).burnup(self.project.id, sprint.id)
        codes = [r["code"] for r in self.Report.reports_meta(self.project.id)["reports"]]
        self.assertIn("burnup", codes)


class TestControlChart(AgileReportCase):
    """M-1055: cycle time per finished issue with a rolling average."""

    def _event(self, issue, kind, days_ago, cycle=0.0):
        when = fields.Datetime.now() - timedelta(days=days_ago)
        self.env["agile.issue.metric.event"].sudo().with_context(allow_agile_metric_event_write=True).create({
            "project_id": self.project.id, "task_id": issue.id, "issue_key": issue.issue_key or issue.name,
            "issue_name": issue.name, "event_type": kind, "event_at": when, "cycle_time_days": cycle,
        })

    def _finished(self, name, days_ago, cycle, started=True):
        issue = self._issue(name, 3)
        if started:
            self._event(issue, "started", days_ago + cycle)
        self._event(issue, "completed", days_ago, cycle)
        return issue

    def test_rolling_and_overall_average_in_finish_order(self):
        for name, ago, cycle in (("A", 6, 2.0), ("B", 4, 4.0), ("C", 2, 6.0)):
            self._finished(name, ago, cycle)
        data = self.Report.control_chart(self.project.id)
        self.assertEqual([i["name"] for i in data["issues"]], ["A", "B", "C"])
        self.assertEqual([i["rolling"] for i in data["issues"]], [2.0, 3.0, 4.0])
        self.assertEqual((data["average"], data["longest"]), (4.0, 6.0))

    def test_rolling_window_keeps_the_last_five(self):
        for index in range(7):
            self._finished(f"I{index}", 8 - index, float(index + 1))
        data = self.Report.control_chart(self.project.id)
        self.assertEqual(data["issues"][-1]["rolling"], 5.0, "the mean of 3, 4, 5, 6 and 7")

    def test_range_filter_and_issues_without_a_start(self):
        self._finished("Old", 120, 3.0)
        self._finished("Recent", 3, 3.0)
        self._finished("No start", 2, 0.0, started=False)
        data = self.Report.control_chart(self.project.id)
        self.assertEqual([i["name"] for i in data["issues"]], ["Recent"])
        wide = self.Report.control_chart(
            self.project.id, fields.Date.to_string(self.today - timedelta(days=150)), fields.Date.to_string(self.today))
        self.assertEqual([i["name"] for i in wide["issues"]], ["Old", "Recent"])

    def test_empty_range_bad_dates_and_access(self):
        self.assertEqual(self.Report.control_chart(self.project.id)["issues"], [])
        with self.assertRaises(UserError):
            self.Report.control_chart(self.project.id, "2026-10-31", "2026-10-01")
        with self.assertRaises(AccessError):
            self.env["agile.report"].with_user(self.outsider).control_chart(self.project.id)
        codes = [r["code"] for r in self.Report.reports_meta(self.project.id)["reports"]]
        self.assertIn("control", codes)


class TestSprintRetro(AgileReportCase):
    def test_notes_wait_for_a_started_sprint_and_show_on_the_report(self):
        sprint = self._sprint()
        with self.assertRaises(UserError):
            sprint.write({"retro_notes": "Too early."})
        self._issue("A", 3).write({"sprint_id": sprint.id})
        sprint.action_confirm_plan()
        sprint.action_start()
        sprint.write({"retro_notes": "Keep the stand-ups short."})
        data = self.Report.sprint_report(self.project.id, sprint.id)
        self.assertEqual(data["sprint"]["retro_notes"], "Keep the stand-ups short.")

    def test_only_a_manager_writes_notes_but_members_read_them(self):
        sprint = self._sprint()
        self._issue("A", 3).write({"sprint_id": sprint.id})
        sprint.action_confirm_plan()
        sprint.action_start()
        with self.assertRaises(UserError):
            sprint.with_user(self.outsider).write({"retro_notes": "Not allowed."})
        self.assertFalse(self.Report.sprint_report(self.project.id, sprint.id)["sprint"]["retro_notes"])


class TestSprintRetroActions(AgileReportCase):
    def _started(self, start_offset=-6):
        sprint = self._sprint(start_offset)
        self._issue("Planned", 3).write({"sprint_id": sprint.id})
        sprint.action_confirm_plan()
        sprint.action_start()
        return sprint

    def test_an_action_lands_in_the_backlog_linked_to_the_sprint(self):
        sprint = self._started()
        row = sprint.with_user(self.manager).agile_retro_add_action("  Shorten stand-ups  ")
        task = self.env["project.task"].browse(row["id"])
        self.assertEqual(task.name, "Shorten stand-ups")
        self.assertEqual(task.retro_sprint_id, sprint)
        self.assertFalse(task.sprint_id)
        self.assertEqual(task.stage_id.agile_status, "backlog")
        data = self.Report.sprint_report(self.project.id, sprint.id)
        self.assertEqual([a["name"] for a in data["retro_actions"]], ["Shorten stand-ups"])
        self.assertTrue(data["can_manage"])

    def test_only_a_manager_adds_and_the_text_is_required(self):
        sprint = self._started()
        with self.assertRaises(UserError):
            sprint.with_user(self.outsider).agile_retro_add_action("Nope")
        with self.assertRaises(UserError):
            sprint.with_user(self.manager).agile_retro_add_action("   ")

    def test_a_draft_sprint_takes_no_actions(self):
        sprint = self._sprint()
        with self.assertRaises(UserError):
            sprint.with_user(self.manager).agile_retro_add_action("Too early")

    def test_open_actions_show_on_the_next_sprint(self):
        first = self._started(-20)
        open_row = first.with_user(self.manager).agile_retro_add_action("Still open")
        done_row = first.with_user(self.manager).agile_retro_add_action("Finished")
        finished = self.env["project.task"].browse(done_row["id"])
        finished.write({"description": "<p>Done soon.</p>", "user_ids": [(4, self.manager.id)]})
        self._finish(finished)
        second = self._sprint(-6)
        data = self.Report.sprint_report(self.project.id, second.id)
        previous = data["previous_actions"]
        self.assertEqual(previous["sprint"]["id"], first.id)
        self.assertEqual([a["id"] for a in previous["actions"]], [open_row["id"]])
        first_data = self.Report.sprint_report(self.project.id, first.id)
        self.assertFalse(first_data["previous_actions"]["actions"])


class TestRecordHistoryNow(AgileReportCase):
    """NU-14: a new project's charts need not wait for the night job."""

    def test_manager_records_today_and_the_cfd_then_has_a_day(self):
        self._issue("One", 3)
        before = self.Report.cfd(self.project.id)
        self.assertTrue(self.Report.record_history_now(self.project.id))
        after = self.Report.cfd(self.project.id)
        self.assertGreaterEqual(len(after["days"]), 1)
        self.assertGreaterEqual(len(after["days"]), len(before["days"]))

    def test_only_a_manager_may_record(self):
        with self.assertRaises(Exception) as caught:
            self.env["agile.report"].with_user(self.outsider).record_history_now(self.project.id)
        self.assertIsInstance(caught.exception, (AccessError, UserError))
