from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.safe_eval import safe_eval

SPRINT_ORDER = {"in_progress": 0, "done": 1, "draft": 2}
CFD_STATUSES = ["done", "review", "progress", "ready", "backlog"]  # bottom band first
CFD_LABELS = {"backlog": "Backlog", "ready": "To Do", "progress": "In Progress", "review": "Review", "done": "Done"}
MAX_DAYS = 366
ROLLING_WINDOW = 5  # issues in the control chart's rolling average
CONTROL_DEFAULT_DAYS = 90
GROUPS = ("completed", "carried", "added", "removed", "planned")

# Reports that open one of the existing delivery screens, limited to the project (R-301).
# Each entry: the action to reuse and the field that holds the project on its model.
NATIVE_REPORTS = {
    "burndown": ("agile_community.agile_metric_burndown_action", "project_id"),
    "velocity": ("agile_community.agile_sprint_velocity_action", "project_id"),
    "throughput": ("agile_community.agile_issue_metric_event_action", "project_id"),
    "flow": ("agile_community.agile_metric_snapshot_action", "project_id"),
}

SPRINT_ONLY_REPORTS = ("sprint", "burnup", "velocity", "burndown")  # a Kanban project has no sprints (NU-49)



class ProjectProject(models.Model):
    _inherit = "project.project"

    def action_open_agile_reports(self):
        self.ensure_one()
        self._check_agile_metrics_access()
        return {
            "type": "ir.actions.client",
            "tag": "agile_community.reports",
            "name": _("Reports"),
            "params": {"project_id": self.id},
            # Kept in the breadcrumb: params are lost when the page is reopened with the Back button.
            "context": {"active_id": self.id, "default_project_id": self.id},
        }


DEEP_LINK_REPORTS = {"sprint": "sprint_id", "epic": "target_id", "release": "target_id"}


class AgileReport(models.AbstractModel):
    _name = "agile.report"
    _description = "Agile Reports"

    # ---- shared -------------------------------------------------------------------

    @api.model
    def _project(self, project_id):
        project = self.env["project.project"].browse(project_id).exists()
        if not project:
            raise UserError(_("Open the reports from their project."))
        project._check_agile_metrics_access()
        return project

    @api.model
    def record_history_now(self, project_id):
        """Record today's figures now, so a new project's charts do not wait for the night job (NU-14)."""
        project = self._project(project_id)
        if project._agile_role_for_user() != "manager":
            raise UserError(_("Only a project manager can record today's figures."))
        metric = self.env["agile.metric.snapshot"].sudo()
        metric._capture_project(project)
        for sprint in project.sprint_ids.filtered(lambda row: row.state == "in_progress"):
            metric._capture_sprint(sprint)
        return True

    @api.model
    def _readable(self, task_ids):
        """The tasks of the list the current user may read, and how many were hidden."""
        visible = self.env["project.task"].search([("id", "in", list(task_ids))])
        return visible, len(set(task_ids)) - len(visible)

    @api.model
    def reports_meta(self, project_id):
        project = self._project(project_id)
        sprints = sorted(
            project.sprint_ids,
            key=lambda s: (SPRINT_ORDER.get(s.state, 3), -(s.date_start.toordinal() if s.date_start else 0), -s.id),
        )
        return {
            "project": {"id": project.id, "name": project.name},
            "reports": [report for report in [
                {"code": "sprint", "group": _("Sprint"), "label": _("Sprint report"),
                 "question": _("What did the sprint deliver?")},
                {"code": "burnup", "group": _("Sprint"), "label": _("Sprint burnup"),
                 "question": _("Are we on pace to finish the sprint, and did the scope grow?")},
                {"code": "velocity", "group": _("Sprint"), "label": _("Velocity"), "native": True,
                 "question": _("How much do we finish per sprint?")},
                {"code": "cfd", "group": _("Flow"), "label": _("Cumulative flow"),
                 "question": _("Where is the work piling up?")},
                {"code": "control", "group": _("Flow"), "label": _("Control chart"),
                 "question": _("How long does an issue take, and is that changing?")},
                {"code": "flow", "group": _("Flow"), "label": _("Daily delivery flow"), "native": True,
                 "question": _("How many points sat in each status each day?")},
                {"code": "history", "group": _("Flow"), "label": _("Delivery history"), "native": True,
                 "question": _("How did remaining points change over time?")},
                {"code": "throughput", "group": _("Flow"), "label": _("Throughput and cycle time"), "native": True,
                 "question": _("How fast does work get done?")},
                {"code": "epic", "group": _("Scope"), "label": _("Epic burndown"),
                 "question": _("How much of this epic is left?")},
                {"code": "release", "group": _("Scope"), "label": _("Release burndown"),
                 "question": _("How much of this release is left?")},
            ] if project.use_scrum or report["code"] not in SPRINT_ONLY_REPORTS],
            "epics": [{"id": e.id, "name": e.name, "key": e.issue_key or ""} for e in self.env["project.task"].search([
                ("project_id", "=", project.id), ("agile_is_epic", "=", True), ("agile_issue", "=", True),
                ("stage_id.agile_status", "!=", "canceled")], order="sequence, id")],
            "releases": [{"id": v.id, "name": v.name} for v in self.env["project.version"].search(
                [("project_id", "=", project.id)], order="id desc")],
            "sprints": [
                {"id": s.id, "name": s.name, "state": s.state,
                 "date_start": fields.Date.to_string(s.date_start), "date_end": fields.Date.to_string(s.date_end)}
                for s in sprints
            ],
        }

    @api.model
    def report_action(self, project_id, report, record_id):
        """Open the Reports page on one report for a sprint, epic or release (used by their buttons)."""
        project = self._project(project_id)
        if report not in DEEP_LINK_REPORTS:
            raise UserError(_("That report cannot be opened from here."))
        params = {"project_id": project.id, "report": report, DEEP_LINK_REPORTS[report]: int(record_id)}
        return {
            "type": "ir.actions.client",
            "tag": "agile_community.reports",
            "name": _("Reports"),
            "params": params,
            "context": {"active_id": project.id, "default_project_id": project.id},
        }

    @api.model
    def native_report_action(self, project_id, code):
        """An existing delivery screen (burndown, velocity, ...) limited to one project."""
        project = self._project(project_id)
        if code == "history":
            action = project.action_view_agile_reports()
            action["context"] = dict(action["context"], agile_sidebar_entry="reports")
            # The web client needs "views" in an action it did not load itself.
            action["views"] = [(False, mode) for mode in action["view_mode"].split(",")]
            return action
        if code not in NATIVE_REPORTS:
            raise UserError(_("Unknown report: %s", code))
        xml_id, field = NATIVE_REPORTS[code]
        action = self.env["ir.actions.act_window"]._for_xml_id(xml_id)
        domain = action.get("domain") or "[]"
        domain = safe_eval(domain) if isinstance(domain, str) else domain
        action["domain"] = list(domain) + [(field, "=", project.id)]
        action["context"] = {
            "default_project_id": project.id,
            # The sidebar keeps Reports highlighted although the model is another one.
            "agile_sidebar_entry": "reports",
        }
        return action

    # ---- R-406: sprint report -------------------------------------------------------

    @api.model
    def _left_sprint(self, sprint):
        """{task_id: when it last left the sprint}, read from the tracked Sprint field."""
        values = self.env["mail.tracking.value"].sudo().search([
            ("field_id.name", "=", "sprint_id"), ("field_id.model", "=", "project.task"),
            ("old_value_integer", "=", sprint.id),
        ])
        left = {}
        for value in values:
            message = value.mail_message_id
            if message.model == "project.task" and message.res_id:
                left[message.res_id] = max(left.get(message.res_id, value.create_date), value.create_date)
        return left

    @api.model
    def _sprint_close_date(self, sprint):
        if sprint.state != "done":
            return None
        closed = self.env["agile.metric.snapshot"].sudo().search(
            [("sprint_id", "=", sprint.id), ("capture_kind", "=", "closed")], order="captured_at desc", limit=1)
        return (closed.captured_at or sprint.write_date).date()

    @api.model
    def _sprint_sets(self, sprint):
        """Task ids of one sprint grouped as the report counts them, and the points per task.

        Planned is the confirmed plan. Left is everything that was taken out of the sprint: before the day
        the sprint closed it is "removed", on that day or later it is "carried over" (unfinished at close).
        """
        sprint = sprint.sudo()
        commits = sprint.commitment_ids.sorted("revision")
        points = {}
        initial = set()
        for line in commits[-1:].line_ids:
            if line.task_id and not line.has_sprint_children:
                initial.add(line.task_id.id)
                points[line.task_id.id] = line.story_points_snapshot if line.estimated_snapshot else 0.0
        tasks = sprint.task_ids.filtered(lambda t: not t.child_ids.filtered(lambda c: c.sprint_id == sprint))
        current = set(tasks.ids)
        for task in tasks:
            points.setdefault(task.id, task._scrum_estimate()[1] if task._scrum_estimate()[0] else 0.0)
        done = {t.id for t in tasks if t.state == "1_done"}
        canceled = {t.id for t in tasks if t.state == "1_canceled"}
        close_date = self._sprint_close_date(sprint)
        removed, carried = set(), set()
        Task = self.env["project.task"].sudo()
        for task_id, when in self._left_sprint(sprint).items():
            if task_id in current or task_id not in initial:
                continue
            task = Task.browse(task_id).exists()
            if not task or task.state in ("1_done", "1_canceled"):
                continue
            points.setdefault(task_id, task._scrum_estimate()[1] if task._scrum_estimate()[0] else 0.0)
            (carried if close_date and when.date() >= close_date else removed).add(task_id)
        return {
            "initial": initial, "done": done, "open": current - done - canceled,
            "added": (current - initial) - canceled, "removed": removed, "carried": carried, "points": points,
        }

    @api.model
    def sprint_report(self, project_id, sprint_id):
        project = self._project(project_id)
        sprint = project.sprint_ids.filtered(lambda s: s.id == sprint_id)
        if not sprint:
            raise UserError(_("Choose a sprint of this project."))
        sets = self._sprint_sets(sprint)
        closed = sprint.state == "done"
        groups = {
            "planned": sets["initial"],
            "completed": sets["done"],
            "carried": sets["carried"] if closed else sets["open"],
            "added": sets["added"],
            "removed": sets["removed"],
        }
        points = sets["points"]
        data = {"estimate_unit": project.scrum_estimate_unit, "sprint": {"id": sprint.id, "name": sprint.name, "state": sprint.state, "goal": sprint.description or "", "retro_notes": sprint.retro_notes or "",
                           "date_start": fields.Date.to_string(sprint.date_start),
                           "date_end": fields.Date.to_string(sprint.date_end)},
                "retro_actions": sprint.agile_retro_actions(),
                "previous_actions": sprint.agile_open_retro_actions(),
                "can_manage": bool(sprint.can_manage_project_sprint),
                "so_far": not closed, "groups": {}, "no_plan": not sets["initial"] and not sets["added"] and not sets["done"]}
        for code in GROUPS:
            ids = groups[code]
            visible, hidden = self._readable(ids)
            data["groups"][code] = {
                "count": len(ids),
                "points": round(sum(points.get(i, 0.0) for i in ids), 2),
                "hidden": hidden,
                "issues": [self._issue_row(t, points.get(t.id, 0.0)) for t in visible.sorted(lambda t: (t.sequence, t.id))],
            }
        planned = data["groups"]["planned"]["points"]
        done_points = data["groups"]["completed"]["points"]
        data["delivered"] = {
            "planned_points": planned, "completed_points": done_points,
            "percent": round(100 * done_points / planned) if planned else None,
        }
        return data

    @api.model
    def _issue_row(self, task, points):
        destination = task.sprint_id.name if task.sprint_id else _("Backlog")
        return {"id": task.id, "key": task.issue_key or "", "name": task.name,
                "status": task.stage_id.name or "", "points": points, "where": destination}

    @api.model
    def sprint_report_issues(self, project_id, sprint_id, group):
        """The list behind one tile, as an action the web client opens."""
        project = self._project(project_id)
        data = self.sprint_report(project_id, sprint_id)
        if group not in data["groups"]:
            raise UserError(_("Unknown report group."))
        ids = [row["id"] for row in data["groups"][group]["issues"]]
        action = project.action_open_agile_backlog()
        labels = {"completed": _("completed"), "carried": _("carried over"), "added": _("added"),
                  "removed": _("removed"), "planned": _("planned at the start")}
        action["name"] = f"{data['sprint']['name']}: {labels[group]}"
        action["domain"] = [("id", "in", ids)]
        action["context"] = {k: v for k, v in action["context"].items() if k != "search_default_agile_hide_completed"}
        return action

    # ---- R-405: cumulative flow -----------------------------------------------------

    @api.model
    def _range(self, project, date_from, date_to):
        today = fields.Date.context_today(project)
        end = fields.Date.to_date(date_to) if date_to else today
        start = fields.Date.to_date(date_from) if date_from else end - timedelta(days=29)
        if start > end:
            raise UserError(_("The start date must be on or before the end date."))
        if (end - start).days >= MAX_DAYS:
            raise UserError(_("Choose a range of at most a year."))
        return start, end

    @api.model
    def _flow_domain(self, project, start, end):
        return [
            ("project_id", "=", project.id), ("sprint_id", "=", False),
            ("capture_kind", "=", "daily"), ("snapshot_date", ">=", start), ("snapshot_date", "<=", end),
        ]

    @api.model
    def cfd(self, project_id, date_from=None, date_to=None):
        """Issues per status for each day with a daily snapshot, Done at the bottom."""
        project = self._project(project_id)
        start, end = self._range(project, date_from, date_to)
        rows = self.env["agile.metric.snapshot.line"].sudo()._read_group(
            self._flow_domain(project, start, end), ["snapshot_date:day", "status"], ["issue_count:sum"])
        days = {}
        for day, status, count in rows:
            days.setdefault(day, {s: 0 for s in CFD_STATUSES})
            if status in days[day]:
                days[day][status] += count
        return {
            "from": fields.Date.to_string(start), "to": fields.Date.to_string(end),
            "statuses": [{"code": s, "label": CFD_LABELS[s]} for s in CFD_STATUSES],
            "days": [{"date": fields.Date.to_string(d), "counts": days[d], "total": sum(days[d].values())}
                     for d in sorted(days)],
        }

    @api.model
    def cfd_issues(self, project_id, day, status):
        """The issues that were in a status on a day, as a list action."""
        project = self._project(project_id)
        if status not in CFD_LABELS:
            raise UserError(_("Unknown status."))
        day = fields.Date.to_date(day)
        lines = self.env["agile.metric.snapshot.line"].sudo().search(self._flow_domain(project, day, day) + [
            ("status", "=", status)])
        visible, _hidden = self._readable(lines.task_id.ids)
        action = project.action_open_agile_backlog()
        action["name"] = _("%(status)s on %(day)s", status=CFD_LABELS[status], day=fields.Date.to_string(day))
        action["domain"] = [("id", "in", visible.ids)]
        action["context"] = {k: v for k, v in action["context"].items() if k != "search_default_agile_hide_completed"}
        return action

    # ---- R-407: epic and release burndown --------------------------------------------

    @api.model
    def _burndown_tasks(self, project, kind, target_id):
        """The issues of an epic or a release as they are today (readable by the viewer)."""
        Task = self.env["project.task"]
        if kind == "epic":
            epic = Task.search([("id", "=", target_id), ("project_id", "=", project.id), ("agile_is_epic", "=", True)])
            if not epic:
                raise UserError(_("Choose an epic of this project."))
            return Task.search([("parent_id", "=", epic.id), ("agile_issue", "=", True), ("agile_is_epic", "=", False)])
        if kind == "release":
            release = self.env["project.version"].search([("id", "=", target_id), ("project_id", "=", project.id)])
            if not release:
                raise UserError(_("Choose a release of this project."))
            return Task.search([("version_id", "=", release.id), ("agile_issue", "=", True), ("agile_is_epic", "=", False)])
        raise UserError(_("Unknown report."))

    @api.model
    def _burndown_domain(self, project, task_ids, start, end):
        return self._flow_domain(project, start, end) + [
            ("task_id", "in", list(task_ids)), ("status", "!=", "canceled")]

    @api.model
    def burndown(self, project_id, kind, target_id, date_from=None, date_to=None):
        """Remaining points per day for one epic or release, with the scope line (total points)."""
        project = self._project(project_id)
        start, end = self._range(project, date_from, date_to)
        tasks = self._burndown_tasks(project, kind, target_id)
        rows = self.env["agile.metric.snapshot.line"].sudo()._read_group(
            self._burndown_domain(project, tasks.ids, start, end), ["snapshot_date:day"],
            ["remaining_points:sum", "story_points:sum", "issue_count:sum"])
        days = [{
            "date": fields.Date.to_string(day), "remaining": round(remaining, 2), "scope": round(scope, 2),
            "done": round(scope - remaining, 2), "issues": count,
        } for day, remaining, scope, count in sorted(rows, key=lambda r: r[0])]
        unestimated = len(tasks.filtered(lambda t: not t._scrum_estimate()[0] and t.agile_status != "canceled"))
        return {
            "estimate_unit": project.scrum_estimate_unit,
            "from": fields.Date.to_string(start), "to": fields.Date.to_string(end), "days": days,
            "issue_count": len(tasks), "unestimated": unestimated,
        }

    @api.model
    def control_chart(self, project_id, date_from=None, date_to=None):
        """Cycle time per finished issue with a rolling average (M-1055), from the first Done events."""
        project = self._project(project_id)
        today = fields.Date.context_today(project)
        end = fields.Date.to_date(date_to) if date_to else today
        start = fields.Date.to_date(date_from) if date_from else end - timedelta(days=CONTROL_DEFAULT_DAYS - 1)
        if start > end:
            raise UserError(_("The start date must be on or before the end date."))
        if (end - start).days >= MAX_DAYS:
            raise UserError(_("Choose a range of at most a year."))
        events = self.env["agile.issue.metric.event"].sudo().search([
            ("project_id", "=", project.id), ("event_type", "=", "completed"),
            ("event_at", ">=", fields.Datetime.to_string(start)),
            ("event_at", "<", fields.Datetime.to_string(end + timedelta(days=1))),
        ], order="event_at, id")
        # An issue that went straight to Done has no start to measure from, so it has no cycle time.
        started = self.env["agile.issue.metric.event"].sudo().search([
            ("task_id", "in", events.task_id.ids), ("event_type", "=", "started")]).task_id
        measured = events.filtered(lambda e: e.task_id in started)
        visible, hidden = self._readable(measured.task_id.ids)
        kept = measured.filtered(lambda e: e.task_id.id in visible.ids)
        issues, window = [], []
        for event in kept:
            window = (window + [event.cycle_time_days])[-ROLLING_WINDOW:]
            issues.append({
                "task_id": event.task_id.id or False, "key": event.issue_key, "name": event.issue_name,
                "date": fields.Date.to_string(event.event_at.date()), "days": round(event.cycle_time_days, 2),
                "rolling": round(sum(window) / len(window), 2),
            })
        days = [issue["days"] for issue in issues]
        return {
            "from": fields.Date.to_string(start), "to": fields.Date.to_string(end), "window": ROLLING_WINDOW,
            "issues": issues, "average": round(sum(days) / len(days), 2) if days else 0.0,
            "longest": max(days) if days else 0.0, "hidden": hidden,
        }

    @api.model
    def burnup(self, project_id, sprint_id):
        """Points done per day against the sprint scope (M-1052), from the daily sprint snapshots."""
        project = self._project(project_id)
        sprint = project.sprint_ids.filtered(lambda s: s.id == sprint_id)
        if not sprint:
            raise UserError(_("Choose a sprint of this project."))
        by_day = project.sudo()._agile_sprint_snapshots(sprint)
        days = [
            {"date": fields.Date.to_string(day), "done": round(scope - left, 2), "scope": round(scope, 2),
             "remaining": round(left, 2), "scope_changed": changed}
            for day, (left, scope, changed) in sorted(by_day.items())
        ]
        return {
            "estimate_unit": project.scrum_estimate_unit,
            "sprint": {"id": sprint.id, "name": sprint.name, "state": sprint.state},
            "days": days,
        }

    @api.model
    def burndown_issues(self, project_id, kind, target_id, day):
        """The issues of the epic or release that were still open on a day."""
        project = self._project(project_id)
        day = fields.Date.to_date(day)
        tasks = self._burndown_tasks(project, kind, target_id)
        lines = self.env["agile.metric.snapshot.line"].sudo().search(
            self._burndown_domain(project, tasks.ids, day, day) + [("status", "!=", "done")])
        visible, _hidden = self._readable(lines.task_id.ids)
        action = project.action_open_agile_backlog()
        action["name"] = _("Open on %s", fields.Date.to_string(day))
        action["domain"] = [("id", "in", visible.ids)]
        action["context"] = {k: v for k, v in action["context"].items() if k != "search_default_agile_hide_completed"}
        return action
