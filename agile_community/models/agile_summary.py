from datetime import timedelta

from odoo import _, fields, models
from odoo.tools import html2plaintext

FLOW_DAYS = 30
ACTIVITY_LIMIT = 8
STATUS_ORDER = ("ready", "progress", "review", "done")


class ProjectProject(models.Model):
    _inherit = "project.project"

    def _agile_summary_scope(self):
        """Issues the Summary charts describe: the active sprint, or all work on a Kanban project."""
        self.ensure_one()
        domain = [
            ("project_id", "=", self.id),
            ("agile_issue", "=", True),
            ("active", "=", True),
            ("agile_is_epic", "=", False),
            ("stage_id.agile_status", "!=", "canceled"),
        ]
        if self.agile_method == "scrum":
            # One chosen active sprint, or every active sprint together.
            chosen = self.env.context.get("agile_summary_sprint_id")
            sprints = self._agile_active_sprints()
            if chosen:
                sprints = sprints.filtered(lambda row: row.id == chosen)
            if sprints:
                domain.append(("sprint_id", "in", sprints.ids))
            else:
                domain.append(("stage_id.agile_status", "!=", "backlog"))
        return domain

    def action_open_agile_summary(self):
        self.ensure_one()
        self._check_agile_metrics_access()
        return {
            "type": "ir.actions.client",
            "tag": "agile_community.summary",
            "name": _("Summary"),
            "params": {"project_id": self.id},
            # Kept in the breadcrumb: params are lost when the page is reopened with the Back button.
            "context": {"active_id": self.id, "default_project_id": self.id},
        }

    def project_update_all_action(self):
        """The project's Dashboard link opens the Agile Summary for Agile team members (S-204)."""
        if (
            len(self) == 1
            and self.agile_enabled
            and self._agile_role_for_user(self.env.user) != "none"
        ):
            return self.action_open_agile_summary()
        return super().project_update_all_action()

    def agile_summary_data(self, sprint_id=None):
        """Everything the Summary page shows, in one call (S-201).

        Builds on the Overview data (pulse and counts) and adds the extra counts, the status
        and type mix, created versus resolved, workload, epics, the next release and recent
        activity. Access is the Overview's: any member of the Agile team.
        """
        self.ensure_one()
        # sprint_id narrows everything to one active sprint; without it all active sprints count.
        self = self.with_context(agile_summary_sprint_id=sprint_id or False)
        data = self.agile_pulse_data(sprint_id=sprint_id)
        tasks = self.env["project.task"]
        counts = data["counts"]
        for metric in ("unassigned", "unestimated"):
            counts[metric] = tasks.search_count(self._agile_metric_domain(metric))
        data.update({
            "status": self._agile_summary_status(),
            "in_backlog": tasks.search_count(
                self._agile_summary_scope() + [("stage_id.agile_status", "=", "backlog")]
            ),
            "types": self._agile_summary_types(),
            "flow": self._agile_summary_flow(),
            "workload": self._agile_summary_workload(),
            "epics": self.agile_backlog_epics()["epics"],
            "release": self._agile_summary_release(),
            "activity": self._agile_summary_activity(),
            "layout": self.agile_summary_layout(),
        })
        return data

    def _agile_summary_status(self):
        stage_status = {
            stage.id: stage.agile_status
            for stage in self.env["project.task.type"].with_context(active_test=False).search(
                [("project_ids", "=", self.id)]
            )
        }
        by_status = dict.fromkeys(STATUS_ORDER, 0)
        for stage, count in self.env["project.task"]._read_group(
            self._agile_summary_scope(), ["stage_id"], ["__count"]
        ):
            status = stage_status.get(stage.id)
            if status in by_status:
                by_status[status] += count
        return [{"status": status, "count": by_status[status]} for status in STATUS_ORDER]

    def _agile_summary_types(self):
        rows = self.env["project.task"]._read_group(
            self._agile_summary_scope(), ["agile_task_type_id"], ["__count"], order="__count desc"
        )
        return [
            {"name": task_type.name if task_type else _("No type"), "count": count}
            for task_type, count in rows
        ]

    def _agile_summary_flow(self):
        """Issues created and resolved on each of the last 30 days."""
        today = fields.Date.context_today(self)
        first = today - timedelta(days=FLOW_DAYS - 1)
        start = fields.Datetime.to_datetime(first)
        created = self.env["project.task"]._read_group(
            [
                ("project_id", "=", self.id),
                ("agile_issue", "=", True),
                ("agile_is_epic", "=", False),
                ("create_date", ">=", start),
            ],
            ["create_date:day"],
            ["__count"],
        )
        # The event table keeps what the metrics screens use, so the totals agree with them.
        resolved = self.env["agile.issue.metric.event"].sudo()._read_group(
            [
                ("project_id", "=", self.id),
                ("event_type", "=", "completed"),
                ("event_at", ">=", start),
            ],
            ["event_at:day"],
            ["__count"],
        )
        created_by_day = {fields.Date.to_date(day): count for day, count in created}
        resolved_by_day = {fields.Date.to_date(day): count for day, count in resolved}
        days = [first + timedelta(days=n) for n in range(FLOW_DAYS)]
        return {
            "days": [fields.Date.to_string(day) for day in days],
            "created": [created_by_day.get(day, 0) for day in days],
            "resolved": [resolved_by_day.get(day, 0) for day in days],
        }

    def _agile_summary_workload(self):
        """Open issues and points per person; unassigned work is its own row."""
        tasks = self.env["project.task"]
        domain = self._agile_metric_domain("open")
        measure = "__count" if self.scrum_estimate_unit == "issues" else "story_points:sum"
        rows = tasks._read_group(domain, ["user_ids"], ["__count", measure])
        people = [
            {"id": user.id, "name": user.name, "issues": count, "points": points or 0.0}
            for user, count, points in rows
            if user
        ]
        people.sort(key=lambda row: (-row["issues"], row["name"]))
        unassigned = tasks._read_group(
            self._agile_metric_domain("unassigned"), [], ["__count", measure]
        )
        count, points = unassigned[0] if unassigned else (0, 0.0)
        return {
            "people": people,
            "unassigned": {"issues": count, "points": points or 0.0},
        }

    def _agile_summary_release(self):
        """The planned release with the nearest target date."""
        release = self.env["project.version"].search(
            [("project_id", "=", self.id), ("state", "=", "planned")],
            order="release_date asc nulls last, id",
            limit=1,
        )
        if not release:
            return False
        blocked = release.agile_issue_ids.filtered(
            lambda task: task.agile_is_blocked
            and task.stage_id.agile_status not in ("done", "canceled")
        )
        return {
            "id": release.id,
            "name": release.name,
            "target_date": fields.Date.to_string(release.release_date) if release.release_date else False,
            "issue_count": release.issue_count,
            "open_issue_count": release.open_issue_count,
            "done_issue_count": release.done_issue_count,
            "blocked_count": len(blocked),
        }

    def _agile_summary_activity(self):
        """The latest comments and changes on this project's issues."""
        tasks = self.env["project.task"].search(
            [("project_id", "=", self.id), ("agile_issue", "=", True)],
            order="write_date desc, id desc",
            limit=40,
        )
        messages = self.env["mail.message"].search(
            [
                ("model", "=", "project.task"),
                ("res_id", "in", tasks.ids),
                ("message_type", "in", ["comment", "notification", "tracking"]),
            ],
            order="id desc",
            limit=ACTIVITY_LIMIT,
        )
        by_id = {task.id: task for task in tasks}
        rows = []
        for message in messages:
            task = by_id.get(message.res_id)
            text = html2plaintext(message.body or "").strip()
            # Tracking values are not readable by every team member; the message already is.
            tracking = message.sudo().tracking_value_ids
            if not text and tracking:
                text = ", ".join(
                    "%s: %s" % (value.field_id.field_description, value.new_value_char or "")
                    for value in tracking
                )
            rows.append({
                "id": message.id,
                "author": message.author_id.name or _("System"),
                "date": fields.Datetime.to_string(message.date),
                "text": text[:140],
                "task_id": task.id if task else False,
                "issue_key": task.issue_key if task else "",
                "issue_name": task.name if task else "",
            })
        return rows
