from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase, new_test_user


class TestAgileEstimateUnit(TransactionCase):
    """M-1051: a project counts points, hours or issues."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, login="unit_manager", groups="project.group_project_manager")
        cls.project = cls.env["project.project"].with_user(cls.manager).create({
            "name": "Unit project", "privacy_visibility": "employees", "agile_enabled": True,
            "agile_key": "UNT", "agile_method": "scrum", "use_scrum": True,
        })
        today = fields.Date.context_today(cls.project)
        cls.sprint = cls.env["project.sprint"].with_user(cls.manager).create({
            "name": "Unit sprint", "project_id": cls.project.id, "date_start": today,
            "date_option": "custom", "date_end": today + timedelta(days=6),
        })
        cls.tasks = cls.env["project.task"]
        for points in (3, 5):
            cls.tasks |= cls.env["project.task"].with_user(cls.manager).create({
                "name": f"Issue {points}", "project_id": cls.project.id, "description": "Unit issue.",
                "story_points": points, "story_points_estimated": True, "sprint_id": cls.sprint.id,
                "user_ids": [(6, 0, [cls.manager.id])],
            })

    def _unit(self, unit):
        self.project.with_user(self.manager).write({"scrum_estimate_unit": unit})
        self.tasks.invalidate_recordset()
        self.sprint.invalidate_recordset()

    def test_points_is_the_default(self):
        self.assertEqual(self.project.scrum_estimate_unit, "points")
        self.assertEqual(self.sprint.planned_points, 8)

    def test_hours_use_the_same_numbers(self):
        self._unit("hours")
        self.assertEqual(self.sprint.planned_points, 8)
        self.assertEqual(self.project.with_user(self.manager).agile_pulse_data()["estimate_unit"], "hours")

    def test_issue_count_counts_each_issue_as_one(self):
        self._unit("issues")
        self.assertEqual(self.sprint.planned_points, 2)
        self.assertEqual(sum(self.tasks.mapped("sprint_group_points")), 2)
        self.assertEqual(sum(self.tasks.mapped("sprint_group_unestimated_count")), 0)

    def test_issue_count_needs_no_estimate(self):
        self.tasks[0].story_points_estimated = False
        self.assertEqual(self.sprint.planned_points, 5)
        self._unit("issues")
        self.assertEqual(self.sprint.planned_points, 2)
        data = self.project.with_user(self.manager).agile_backlog_sprints()
        self.assertEqual(data["estimate_unit"], "issues")
        self.assertEqual(data["backlog"]["unestimated_count"], 0)

    def test_summary_workload_counts_issues(self):
        self._unit("issues")
        data = self.project.with_user(self.manager).agile_summary_data()
        self.assertEqual(data["estimate_unit"], "issues")
        me = next(row for row in data["workload"]["people"] if row["id"] == self.manager.id)
        self.assertEqual((me["issues"], me["points"]), (2, 2))
        self.assertEqual(data["counts"]["unestimated"], 0)

    def test_confirmed_plan_snapshot_uses_the_unit_at_confirm_time(self):
        self._unit("issues")
        self.sprint.with_user(self.manager).action_confirm_plan()
        lines = self.sprint.commitment_ids.line_ids
        self.assertEqual(lines.mapped("story_points_snapshot"), [1.0, 1.0])
        self._unit("points")
        self.assertEqual(
            self.sprint.commitment_ids.line_ids.mapped("story_points_snapshot"), [1.0, 1.0],
            "a confirmed plan keeps the numbers it was made with",
        )

    def test_change_is_remembered(self):
        self._unit("hours")
        self.assertEqual(self.project.scrum_estimate_unit_before, "points")
        self.assertEqual(self.project.scrum_estimate_unit_changed, fields.Date.context_today(self.project))
        self._unit("hours")
        self.assertEqual(self.project.scrum_estimate_unit_before, "points", "no change, no new note")

    def test_form_warns_when_the_unit_changes(self):
        result = self.project.with_user(self.manager).new(
            {"scrum_estimate_unit": "hours"}, origin=self.project
        )._onchange_scrum_estimate_unit()
        self.assertIn("closed", result["warning"]["message"])
