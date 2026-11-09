from datetime import timedelta

from odoo import _, fields, models

ROWS_PER_TAB = 50
DUE_DAYS = 7
TABS = ("assigned", "review", "blocked", "due")


class ProjectProject(models.Model):
    _inherit = "project.project"

    def action_open_agile_your_work(self):
        self.ensure_one()
        self._check_agile_metrics_access()
        return {
            "type": "ir.actions.client",
            "tag": "agile_community.your_work",
            "name": _("Your work"),
            "params": {"project_id": self.id},
            # Kept in the breadcrumb: params are lost when the page is reopened with the Back button.
            "context": {"active_id": self.id, "default_project_id": self.id},
        }

    def _agile_your_work_domain(self, tab):
        """The issues of this project behind each Your work tab (the top-menu My Work, one project)."""
        self.ensure_one()
        user = self.env.user
        open_issue = ("stage_id.agile_status", "not in", ["done", "canceled"])
        base = [
            ("project_id", "=", self.id),
            ("agile_issue", "=", True),
            ("active", "=", True),
            ("agile_is_epic", "=", False),
        ]
        mine = ("user_ids", "in", user.id)
        if tab == "assigned":
            return base + [mine, open_issue]
        if tab == "review":
            return base + [("stage_id.agile_status", "=", "review")]
        if tab == "blocked":
            return base + [mine, ("agile_is_blocked", "=", True), open_issue]
        start = self._agile_local_day_start_utc()
        end = start + timedelta(days=DUE_DAYS + 1)
        return base + [
            mine,
            ("date_deadline", ">=", fields.Datetime.to_string(start)),
            ("date_deadline", "<", fields.Datetime.to_string(end)),
            open_issue,
        ]

    def agile_your_work_data(self):
        """Counts and the first rows of each Your work tab, in one call (W-501)."""
        self.ensure_one()
        self._check_agile_metrics_access()
        tasks = self.env["project.task"]
        tabs = {}
        for tab in TABS:
            domain = self._agile_your_work_domain(tab)
            found = tasks.search(domain, order="priority desc, date_deadline asc, id", limit=ROWS_PER_TAB)
            tabs[tab] = {
                "count": tasks.search_count(domain),
                "rows": [
                    {
                        "id": task.id,
                        "issue_key": task.issue_key or "",
                        "name": task.name,
                        "status": task.agile_status,
                        "points": task.story_points if task.story_points_estimated else False,
                        "blocked": bool(task.agile_is_blocked),
                        "sprint": task.sprint_id.name or "",
                        "deadline": fields.Datetime.to_string(task.date_deadline) if task.date_deadline else False,
                    }
                    for task in found
                ],
            }
        return {"project": {"id": self.id, "name": self.display_name}, "tabs": tabs}
