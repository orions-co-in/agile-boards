from types import SimpleNamespace

from odoo import api, fields, models, _
from odoo.exceptions import UserError


METRIC_ISSUE_DOMAIN = [
    ("agile_issue", "=", True),
    ("active", "=", True),
    ("agile_is_epic", "=", False),
    ("child_ids", "=", False),
]
METRIC_SNAPSHOT_BATCH_SIZE = 500


class AgileMetricSnapshot(models.Model):
    _name = "agile.metric.snapshot"
    _description = "Agile Daily Metric Snapshot"
    _order = "captured_at desc, id desc"

    snapshot_key = fields.Char(required=True, readonly=True, copy=False, index=True)
    project_id = fields.Many2one(
        "project.project", required=True, readonly=True, ondelete="restrict", index=True
    )
    sprint_id = fields.Many2one(
        "project.sprint", readonly=True, ondelete="restrict", index=True
    )
    snapshot_date = fields.Date(required=True, readonly=True, index=True)
    captured_at = fields.Datetime(required=True, readonly=True, index=True)
    capture_kind = fields.Selection(
        [("daily", "Daily"), ("started", "Sprint started"), ("closed", "Sprint completed")],
        required=True,
        readonly=True,
    )
    scope_change_count = fields.Integer(readonly=True, default=0)
    line_ids = fields.One2many(
        "agile.metric.snapshot.line", "snapshot_id", readonly=True
    )

    _snapshot_key_unique = models.Constraint(
        "unique (snapshot_key)", "A metric snapshot already exists for this period."
    )

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise UserError(_("Metric snapshots are system managed."))
        return super().create(vals_list)

    def write(self, vals):
        raise UserError(_("Metric snapshots cannot be edited."))

    def unlink(self):
        if self.env.context.get("module_uninstall"):
            return super().unlink()
        raise UserError(_("Metric snapshots cannot be deleted."))

    @api.model
    def _capture_project(self, project, capture_kind="daily", captured_at=None):
        project.ensure_one()
        captured_at = captured_at or fields.Datetime.now()
        snapshot_date = captured_at.date()
        key = f"{project.id}:0:{snapshot_date}:{capture_kind}"
        if self.sudo().search_count([("snapshot_key", "=", key)]):
            return self.sudo().search([("snapshot_key", "=", key)], limit=1)

        snapshot = self.sudo().with_context(
            allow_agile_metric_snapshot_write=True
        ).create(
            {
                "snapshot_key": key,
                "project_id": project.id,
                "snapshot_date": snapshot_date,
                "captured_at": captured_at,
                "capture_kind": capture_kind,
            }
        )
        line_model = self.env["agile.metric.snapshot.line"].sudo().with_context(
            allow_agile_metric_snapshot_write=True
        )
        domain = METRIC_ISSUE_DOMAIN + [("project_id", "=", project.id)]
        for tasks in self._iter_snapshot_tasks(domain):
            line_model.create([self._line_values(snapshot, task) for task in tasks])
        return snapshot

    @api.model
    def _capture_sprint(self, sprint, capture_kind="daily", captured_at=None):
        sprint.ensure_one()
        captured_at = captured_at or fields.Datetime.now()
        snapshot_date = captured_at.date()
        key = f"{sprint.project_id.id}:{sprint.id}:{snapshot_date}:{capture_kind}"
        existing = self.sudo().search([("snapshot_key", "=", key)], limit=1)
        if existing:
            return existing

        previous = self.sudo().search(
            [("sprint_id", "=", sprint.id)], order="captured_at desc, id desc", limit=1
        )
        domain = METRIC_ISSUE_DOMAIN + [("sprint_id", "=", sprint.id)]
        line_model = self.env["agile.metric.snapshot.line"].sudo().with_context(
            allow_agile_metric_snapshot_write=True
        )
        current_ids = set()
        for tasks in self._iter_snapshot_tasks(domain):
            current_ids.update(tasks.ids)
        previous_ids = set(previous.line_ids.mapped("task_id").ids)
        scope_change_count = len(current_ids.symmetric_difference(previous_ids)) if previous else 0
        snapshot = self.sudo().with_context(
            allow_agile_metric_snapshot_write=True
        ).create(
            {
                "snapshot_key": key,
                "project_id": sprint.project_id.id,
                "sprint_id": sprint.id,
                "snapshot_date": snapshot_date,
                "captured_at": captured_at,
                "capture_kind": capture_kind,
                "scope_change_count": scope_change_count,
            }
        )
        latest_commitment = sprint.commitment_ids.sudo().sorted(
            "revision", reverse=True
        )[:1]
        committed = {
            line.task_id.id: line
            for line in latest_commitment.line_ids
            if line.task_id
        }
        for tasks in self._iter_snapshot_tasks(domain):
            line_model.create(
                [
                    self._line_values(snapshot, task, committed.get(task.id))
                    for task in tasks
                ]
            )
        return snapshot

    @api.model
    def _iter_snapshot_tasks(self, domain):
        """Yield stable, bounded issue batches for metric snapshot generation."""
        task_model = self.env["project.task"].sudo()
        last_id = 0
        while True:
            tasks = task_model.search(
                domain + [("id", ">", last_id)],
                order="id",
                limit=METRIC_SNAPSHOT_BATCH_SIZE,
            )
            if not tasks:
                return
            yield tasks
            last_id = tasks[-1].id

    @api.model
    def _line_values(self, snapshot, task, commitment_line=None):
        status = task.agile_status or "backlog"
        task_estimated, task_points = task._scrum_estimate()
        estimated = commitment_line.estimated_snapshot if commitment_line else task_estimated
        points = commitment_line.story_points_snapshot if commitment_line else task_points
        canceled = status == "canceled" or task.state == "1_canceled"
        done = status == "done" or task.state == "1_done"
        return {
            "snapshot_id": snapshot.id,
            "project_id": snapshot.project_id.id,
            "task_id": task.id,
            "issue_key": task.issue_key or task.display_name,
            "issue_name": task.name,
            "status": status,
            "is_blocked": bool(task.agile_is_blocked and not done and not canceled),
            "is_overdue": bool(
                task.date_deadline
                and task.date_deadline.date() < snapshot.snapshot_date
                and not done
                and not canceled
            ),
            "estimated": bool(estimated),
            "story_points": points if estimated else 0.0,
            "remaining_points": points if estimated and not done and not canceled else 0.0,
            "issue_count": 1,
        }

    @api.model
    def _live_sprint_totals(self, sprint):
        """Current (points_left, scope_points) of a sprint, computed like a snapshot."""
        stub = SimpleNamespace(
            id=False,
            project_id=sprint.project_id,
            snapshot_date=fields.Date.context_today(self),
        )
        latest = sprint.commitment_ids.sudo().sorted("revision", reverse=True)[:1]
        committed = {
            line.task_id.id: line for line in latest.line_ids if line.task_id
        }
        left = scope = 0.0
        domain = METRIC_ISSUE_DOMAIN + [("sprint_id", "=", sprint.id)]
        for tasks in self._iter_snapshot_tasks(domain):
            for task in tasks:
                values = self._line_values(stub, task, committed.get(task.id))
                left += values["remaining_points"]
                scope += values["story_points"]
        return left, scope

    @api.model
    def _cron_capture_daily_snapshots(self):
        projects = self.env["project.project"].sudo().search(
            [("agile_enabled", "=", True), ("active", "=", True)]
        )
        metric_model = self.sudo()
        for project in projects:
            metric_model._capture_project(project)
            for sprint in project.sprint_ids.filtered(lambda row: row.state == "in_progress"):
                metric_model._capture_sprint(sprint)


class AgileMetricSnapshotLine(models.Model):
    _name = "agile.metric.snapshot.line"
    _description = "Agile Metric Snapshot Issue"
    _order = "snapshot_id, issue_key, id"

    snapshot_id = fields.Many2one(
        "agile.metric.snapshot", required=True, readonly=True, ondelete="cascade", index=True
    )
    project_id = fields.Many2one(
        "project.project", required=True, readonly=True, ondelete="restrict", index=True
    )
    task_id = fields.Many2one("project.task", readonly=True, ondelete="set null", index=True)
    issue_key = fields.Char(required=True, readonly=True)
    issue_name = fields.Char(required=True, readonly=True)
    snapshot_date = fields.Date(related="snapshot_id.snapshot_date", store=True, readonly=True)
    captured_at = fields.Datetime(related="snapshot_id.captured_at", store=True, readonly=True)
    sprint_id = fields.Many2one(related="snapshot_id.sprint_id", store=True, readonly=True)
    capture_kind = fields.Selection(related="snapshot_id.capture_kind", store=True, readonly=True)
    scope_change_count = fields.Integer(
        related="snapshot_id.scope_change_count", store=True, readonly=True, aggregator="max"
    )
    status = fields.Selection(
        [
            ("backlog", "Backlog"),
            ("ready", "To Do"),
            ("progress", "In Progress"),
            ("review", "Review"),
            ("done", "Done"),
            ("canceled", "Canceled"),
        ],
        required=True,
        readonly=True,
    )
    is_blocked = fields.Boolean(readonly=True)
    is_overdue = fields.Boolean(readonly=True)
    estimated = fields.Boolean(readonly=True)
    story_points = fields.Float(digits=(16, 2), readonly=True, aggregator="sum")
    remaining_points = fields.Float(digits=(16, 2), readonly=True, aggregator="sum")
    issue_count = fields.Integer(readonly=True, default=1, aggregator="sum")

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise UserError(_("Metric snapshot issues are system managed."))
        return super().create(vals_list)

    def write(self, vals):
        raise UserError(_("Metric snapshot issues cannot be edited."))

    def unlink(self):
        if self.env.context.get("module_uninstall"):
            return super().unlink()
        raise UserError(_("Metric snapshot issues cannot be deleted."))

    def action_open_issue(self):
        self.ensure_one()
        if not self.task_id or not self.task_id.has_access("read"):
            raise UserError(_("You no longer have access to this issue."))
        return {
            "type": "ir.actions.act_window",
            "name": self.issue_key,
            "res_model": "project.task",
            "res_id": self.task_id.id,
            "view_mode": "form",
            "target": "current",
        }


class AgileIssueMetricEvent(models.Model):
    _name = "agile.issue.metric.event"
    _description = "Agile Issue First Milestone"
    _order = "event_at desc, id desc"

    project_id = fields.Many2one(
        "project.project", required=True, readonly=True, ondelete="restrict", index=True
    )
    task_id = fields.Many2one("project.task", readonly=True, ondelete="set null", index=True)
    issue_key = fields.Char(required=True, readonly=True)
    issue_name = fields.Char(required=True, readonly=True)
    event_type = fields.Selection(
        [("started", "First entered In Progress"), ("completed", "First entered Done")],
        required=True,
        readonly=True,
        index=True,
    )
    event_at = fields.Datetime(required=True, readonly=True, index=True)
    story_points = fields.Float(digits=(16, 2), readonly=True, aggregator="sum")
    throughput_points = fields.Float(
        string="Throughput Points",
        compute="_compute_throughput_points",
        store=True,
        readonly=True,
        aggregator="sum",
    )
    cycle_time_days = fields.Float(digits=(16, 2), readonly=True, aggregator="avg")

    @api.depends("event_type", "story_points")
    def _compute_throughput_points(self):
        for event in self:
            event.throughput_points = (
                event.story_points if event.event_type == "completed" else 0.0
            )

    _first_milestone_unique = models.Constraint(
        "unique (task_id, event_type)", "Only the first issue milestone can be recorded."
    )

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise UserError(_("Issue metric history is system managed."))
        return super().create(vals_list)

    def write(self, vals):
        raise UserError(_("Issue metric history cannot be edited."))

    def unlink(self):
        if self.env.context.get("module_uninstall"):
            return super().unlink()
        raise UserError(_("Issue metric history cannot be deleted."))

    @api.model
    def _record_first_transition(self, task, event_type, event_at=None):
        task.ensure_one()
        if not task.agile_issue or not task.active:
            return self.browse()
        if self.sudo().search_count(
            [("task_id", "=", task.id), ("event_type", "=", event_type)]
        ):
            return self.browse()
        event_at = event_at or fields.Datetime.now()
        started = self.sudo().search(
            [("task_id", "=", task.id), ("event_type", "=", "started")], limit=1
        )
        cycle_time = False
        if event_type == "completed" and started:
            cycle_time = max(
                0.0,
                (event_at - started.event_at).total_seconds() / 86400.0,
            )
        return self.sudo().with_context(allow_agile_metric_event_write=True).create(
            {
                "project_id": task.project_id.id,
                "task_id": task.id,
                "issue_key": task.issue_key or task.display_name,
                "issue_name": task.name,
                "event_type": event_type,
                "event_at": event_at,
                "story_points": task._scrum_estimate()[1] if task._scrum_estimate()[0] else 0.0,
                "cycle_time_days": cycle_time,
            }
        )

    def action_open_issue(self):
        self.ensure_one()
        if not self.task_id or not self.task_id.has_access("read"):
            raise UserError(_("You no longer have access to this issue."))
        return {
            "type": "ir.actions.act_window",
            "name": self.issue_key,
            "res_model": "project.task",
            "res_id": self.task_id.id,
            "view_mode": "form",
            "target": "current",
        }


class ProjectSprint(models.Model):
    _inherit = "project.sprint"

    def write(self, vals):
        result = super().write(vals)
        target_state = vals.get("state")
        if target_state in ("in_progress", "done"):
            metric_model = self.env["agile.metric.snapshot"].sudo()
            capture_kind = "started" if target_state == "in_progress" else "closed"
            for sprint in self:
                metric_model._capture_sprint(sprint, capture_kind=capture_kind)
        return result

    def action_view_metric_history(self):
        self.ensure_one()
        self.check_access("read")
        return {
            "type": "ir.actions.act_window",
            "name": _("Sprint Burndown History"),
            "res_model": "agile.metric.snapshot.line",
            "view_mode": "graph,pivot,list",
            "domain": [("sprint_id", "=", self.id)],
        }
