from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user


class TestAgileYourWork(TransactionCase):
    """W-501, W-502 and R-301: Your work per project, board chips, the Reports hub."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, login="yw_manager", groups="project.group_project_manager")
        cls.outsider = new_test_user(cls.env, login="yw_outsider", groups="project.group_project_user")
        cls.project = cls._project("YWA")
        cls.other = cls._project("YWB")

    @classmethod
    def _project(cls, key):
        project = cls.env["project.project"].with_user(cls.manager).create({
            "name": f"Work {key}", "privacy_visibility": "employees", "agile_enabled": True,
            "agile_key": key, "agile_method": "scrum",
        })
        cls.env["agile.project.member"].sudo().search([
            ("project_id", "=", project.id), ("user_id", "=", cls.outsider.id)]).unlink()
        return project

    def _issue(self, name, project=None, mine=True, **extra):
        values = {
            "name": name, "project_id": (project or self.project).id, "description": "Work issue.",
            "story_points": 2,
            "user_ids": [(6, 0, [self.manager.id])] if mine else [(5, 0, 0)],
        }
        values.update(extra)
        return self.env["project.task"].with_user(self.manager).create(values)

    def _data(self, project=None):
        return (project or self.project).with_user(self.manager).agile_your_work_data()

    def _keys(self, data, tab):
        return [row["issue_key"] for row in data["tabs"][tab]["rows"]]

    def test_assigned_tab_is_this_projects_open_work_of_the_user(self):
        mine = self._issue("Mine")
        self._issue("Someone else's", mine=False)
        self._issue("Other project", project=self.other)
        finished = self._issue("Finished")
        for step in ("mark_ready", "start", "send_review", "complete"):
            getattr(finished.with_user(self.manager), f"action_agile_{step}")()
        data = self._data()
        self.assertEqual(self._keys(data, "assigned"), [mine.issue_key])
        self.assertEqual(data["tabs"]["assigned"]["count"], 1)

    def test_review_tab_lists_issues_in_review_whoever_has_them(self):
        issue = self._issue("To review", mine=False)
        issue.with_user(self.manager).write({"user_ids": [(6, 0, [self.manager.id])]})
        for step in ("mark_ready", "start", "send_review"):
            getattr(issue.with_user(self.manager), f"action_agile_{step}")()
        issue.with_user(self.manager).write({"user_ids": [(5, 0, 0)]})
        data = self._data()
        self.assertEqual(self._keys(data, "review"), [issue.issue_key])
        self.assertEqual(data["tabs"]["review"]["count"], 1)

    def test_blocked_and_due_tabs(self):
        blocked = self._issue("Blocked one")
        blocked.with_user(self.manager).write({"agile_blocked": True, "agile_block_reason": "Waiting"})
        soon = self._issue("Due soon", date_deadline=fields.Datetime.now() + timedelta(days=2))
        self._issue("Due later", date_deadline=fields.Datetime.now() + timedelta(days=30))
        data = self._data()
        self.assertEqual(self._keys(data, "blocked"), [blocked.issue_key])
        self.assertEqual(self._keys(data, "due"), [soon.issue_key])

    def test_rows_carry_what_the_page_shows(self):
        issue = self._issue("Row", story_points=5)
        row = self._data()["tabs"]["assigned"]["rows"][0]
        self.assertEqual((row["id"], row["name"], row["points"], row["status"]), (issue.id, "Row", 5, "backlog"))

    def test_outsiders_cannot_read_it(self):
        with self.assertRaises(AccessError):
            self.project.with_user(self.outsider).agile_your_work_data()

    def test_sidebar_lists_the_entry_and_counts_assigned_work(self):
        self._issue("Counted")
        data = self.project.with_user(self.manager).agile_sidebar_data()
        self.assertIn("mine", data["entries"])
        self.assertEqual(data["counts"]["mine"], 1)
        action = self.project.with_user(self.manager).agile_sidebar_action("mine")
        self.assertEqual(action["tag"], "agile_community.your_work")

    # ---- W-502: chips are remembered ----

    def test_board_chip_keys_can_be_saved(self):
        project = self.project.with_user(self.manager)
        project.agile_save_board_options(filters=["review", "due", "canceled", "mine"])
        saved = project.agile_board_options()["filters"]
        self.assertEqual(saved, ["review", "due", "canceled", "mine"])
        with self.assertRaises(ValidationError):
            project.agile_save_board_options(filters=["nonsense"])

    # ---- R-301 / R-302: Reports hub ----

    def test_hub_lists_every_report(self):
        meta = self.env["agile.report"].with_user(self.manager).reports_meta(self.project.id)
        codes = [report["code"] for report in meta["reports"]]
        self.assertEqual(
            codes,
            ["sprint", "burnup", "velocity", "cfd", "control"] + (["deploys"] if "agile.deployment" in self.env else [])
            + ["flow", "history", "throughput", "epic", "release"],
        )
        native = {report["code"] for report in meta["reports"] if report.get("native")}
        self.assertEqual(native, {"velocity", "flow", "history", "throughput"})

    def test_native_reports_open_limited_to_the_project(self):
        report = self.env["agile.report"].with_user(self.manager)
        for code in ("burndown", "velocity", "flow", "history", "throughput"):
            action = report.native_report_action(self.project.id, code)
            self.assertIn(("project_id", "=", self.project.id), [tuple(term) for term in action["domain"] if isinstance(term, (list, tuple))], code)
            self.assertEqual(action["context"]["agile_sidebar_entry"], "reports", code)
            self.assertTrue(action.get("views"), code)

    def test_native_report_checks_access_and_code(self):
        report = self.env["agile.report"]
        with self.assertRaises(AccessError):
            report.with_user(self.outsider).native_report_action(self.project.id, "burndown")
        with self.assertRaises(UserError):
            report.with_user(self.manager).native_report_action(self.project.id, "nope")
