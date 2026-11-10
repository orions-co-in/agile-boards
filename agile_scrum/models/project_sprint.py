from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import LazyTranslate
from odoo.tools.float_utils import float_compare
from psycopg2 import IntegrityError

_lt = LazyTranslate(__name__, default_lang="en_US")

DATE_OPTIONS = [
    ("1_weeks", str(_lt("1 Week"))),
    ("2_weeks", str(_lt("2 Weeks"))),
    ("1_months", str(_lt("1 Month"))),
    ("2_months", str(_lt("2 Months"))),
    ("custom", str(_lt("Custom"))),
]


class ProjectSprint(models.Model):
    _name = "project.sprint"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Project Sprint"
    _order = "date_start desc, id desc"
    _date_check = models.Constraint(
        "CHECK (date_start <= date_end)",
        "The end date must be on or after the start date.",
    )
    _one_active_sprint_per_project = models.Constraint(
        "UNIQUE(active_project_id)",
        "A project can have only one active sprint.",
    )

    name = fields.Char(required=True, tracking=True)
    user_ids = fields.Many2many(
        comodel_name="res.users",
        string="Members",
        domain="[('share', '=', False), ('active', '=', True)]",
        tracking=True,
        relation="project_sprint_user_rel",
    )
    description = fields.Text(string="Goal", tracking=True)
    project_id = fields.Many2one(
        comodel_name="project.project",
        string="Project",
        required=True,
        tracking=True,
        ondelete="restrict",
        domain="[('use_scrum', '=', True)]",
    )
    task_ids = fields.One2many(
        comodel_name="project.task",
        inverse_name="sprint_id",
        string="Issues",
        domain="[('project_id', '=', project_id)]",
    )
    date_start = fields.Date(
        string="Start Date", default=fields.Date.context_today, required=True
    )
    date_option = fields.Selection(
        selection=DATE_OPTIONS, default=DATE_OPTIONS[0][0], required=True
    )
    date_end = fields.Date(
        string="End Date",
        required=True,
        compute="_compute_date_end",
        store=True,
        readonly=False,
    )
    state = fields.Selection(
        selection=[
            ("draft", "Planned"),
            ("in_progress", "Active"),
            ("done", "Completed"),
        ],
        default="draft",
        tracking=True,
        copy=False,
    )
    active_project_id = fields.Many2one(
        comodel_name="project.project",
        compute="_compute_active_project_id",
        store=True,
        index=True,
        copy=False,
    )
    tasks_count = fields.Integer(compute="_compute_tasks_count")
    planning_confirmed = fields.Boolean(
        string="Planning Confirmed",
        default=False,
        readonly=True,
        copy=False,
        tracking=True,
    )
    committed_task_count = fields.Integer(
        string="Committed Issues", readonly=True, copy=False
    )
    completed_task_count = fields.Integer(
        string="Completed Issues", readonly=True, copy=False
    )
    scope_change_ids = fields.One2many(
        comodel_name="project.sprint.scope.change",
        inverse_name="sprint_id",
        string="Scope Changes",
        readonly=True,
    )
    scope_change_count = fields.Integer(compute="_compute_scope_change_count")
    commitment_ids = fields.One2many(
        "project.sprint.commitment", "sprint_id", string="Plan History", readonly=True
    )
    commitment_count = fields.Integer(compute="_compute_commitment_count")
    close_summary = fields.Text(readonly=True, copy=False)
    capacity_ids = fields.One2many(
        "project.sprint.capacity",
        "sprint_id",
        string="Member Capacity",
        copy=False,
    )
    planned_points = fields.Float(
        string="Planned Points", compute="_compute_point_capacity_totals"
    )
    unestimated_issue_count = fields.Integer(
        string="Unestimated Issues", compute="_compute_point_capacity_totals"
    )
    capacity_points = fields.Float(
        string="Team Capacity", compute="_compute_point_capacity_totals"
    )
    over_capacity = fields.Boolean(compute="_compute_point_capacity_totals")
    planning_stale = fields.Boolean(compute="_compute_point_capacity_totals")
    can_manage_project_sprint = fields.Boolean(
        compute="_compute_can_manage_project_sprint"
    )
    committed_points_at_close = fields.Float(readonly=True, copy=False)
    completed_points = fields.Float(readonly=True, copy=False)
    correction_ids = fields.One2many(
        "project.sprint.correction",
        "sprint_id",
        string="Corrections",
        readonly=True,
    )

    @api.depends_context("uid")
    @api.depends("project_id")
    def _compute_can_manage_project_sprint(self):
        for sprint in self:
            sprint.can_manage_project_sprint = sprint._is_project_manager_for_project(
                sprint.project_id
            )

    def _is_project_manager_for_project(self, project):
        """Extension point for products with a project-scoped manager role."""
        return bool(
            project and self.env.user.has_group("project.group_project_manager")
        )

    def _check_project_manager_role(self, project=False):
        projects = self.mapped("project_id") if self else project
        for project_record in projects:
            if not self._is_project_manager_for_project(project_record):
                raise UserError(
                    self.env._("Only a Project manager for this project can manage its sprint.")
                )

    @api.depends("commitment_ids")
    def _compute_commitment_count(self):
        for sprint in self:
            sprint.commitment_count = len(sprint.commitment_ids)

    @api.depends("scope_change_ids")
    def _compute_scope_change_count(self):
        for sprint in self:
            sprint.scope_change_count = len(sprint.scope_change_ids)

    @api.depends(
        "task_ids.story_points",
        "task_ids.story_points_estimated",
        "project_id.scrum_estimate_unit",
        "task_ids.state",
        "task_ids.user_ids",
        "task_ids.child_ids",
        "capacity_ids.capacity_points",
        "capacity_ids.user_id.active",
        "commitment_ids.line_ids.story_points_snapshot",
        "commitment_ids.line_ids.estimated_snapshot",
        "commitment_ids.line_ids.has_sprint_children",
        "commitment_ids.line_ids.user_ids",
        "commitment_ids.capacity_line_ids.capacity_points",
        "commitment_ids.capacity_line_ids.user_id.active",
    )
    def _compute_point_capacity_totals(self):
        for sprint in self:
            entries = sprint._get_point_entries()
            sprint.planned_points = sum(
                entry["points"] for entry in entries if entry["estimated"]
            )
            sprint.unestimated_issue_count = sum(
                1 for entry in entries if not entry["estimated"]
            )
            capacity_entries = sprint._get_capacity_entries()
            sprint.capacity_points = sum(
                entry["points"]
                for entry in capacity_entries
                if entry["user"] and entry["user"].active
            )
            sprint.over_capacity = (
                float_compare(
                    sprint.planned_points,
                    sprint.capacity_points,
                    precision_digits=2,
                )
                > 0
            )
            sprint.planning_stale = (
                sprint.state == "draft"
                and sprint.planning_confirmed
                and sprint._is_confirmed_plan_stale()
            )

    def _get_point_entries(self):
        self.ensure_one()
        if self.planning_confirmed and self.commitment_ids:
            entries = []
            for line in self.commitment_ids.sorted("revision", reverse=True)[
                :1
            ].line_ids:
                if line.has_sprint_children:
                    continue
                if line.task_id and line.task_id.state == "1_canceled":
                    continue
                entries.append(
                    {
                        "task": line.task_id,
                        "estimated": line.estimated_snapshot,
                        "points": line.story_points_snapshot,
                        "users": line.user_ids.filtered(
                            lambda user: user.active and not user.share
                        ),
                    }
                )
            return entries
        tasks = self.task_ids
        return [
            {
                "task": task,
                "estimated": task._scrum_estimate()[0],
                "points": task._scrum_estimate()[1],
                "users": task.user_ids.filtered(
                    lambda user: user.active and not user.share
                ),
            }
            for task in tasks
            if task.state != "1_canceled"
            and not (task.child_ids & tasks)
        ]

    def _get_capacity_entries(self):
        self.ensure_one()
        if self.planning_confirmed and self.commitment_ids:
            return [
                {
                    "user": line.user_id,
                    "name": line.user_name,
                    "points": line.capacity_points,
                }
                for line in self.commitment_ids.sorted("revision", reverse=True)[
                    :1
                ].capacity_line_ids
            ]
        return [
            {
                "user": line.user_id,
                "name": line.user_id.name,
                "points": line.capacity_points,
            }
            for line in self.capacity_ids
        ]

    def _active_capacity_members(self):
        self.ensure_one()
        return self.user_ids.filtered(lambda user: user.active and not user.share)

    def _is_confirmed_plan_stale(self):
        self.ensure_one()
        if not self.planning_confirmed:
            return True
        latest = self.commitment_ids.sorted("revision", reverse=True)[:1]
        if not latest:
            return True
        current_tasks = self.task_ids
        if set(latest.line_ids.mapped("task_id").ids) != set(current_tasks.ids):
            return True
        for task in current_tasks:
            line = latest.line_ids.filtered(lambda item: item.task_id == task)
            if not line:
                return True
            if (
                line.estimated_snapshot != task._scrum_estimate()[0]
                or float_compare(
                    line.story_points_snapshot,
                    task._scrum_estimate()[1],
                    precision_digits=2,
                )
                != 0
                or set(line.user_ids.ids) != set(task.user_ids.ids)
                or line.has_sprint_children != bool(task.child_ids & current_tasks)
            ):
                return True
        current_capacity = {
            line.user_id.id: line.capacity_points for line in self.capacity_ids
        }
        snapshot_capacity = {
            line.user_id.id: line.capacity_points
            for line in latest.capacity_line_ids
            if line.user_id
        }
        return current_capacity != snapshot_capacity

    @api.depends("project_id", "state", "project_id.allow_multiple_active_sprints")
    def _compute_active_project_id(self):
        # The unique index on this field is what limits a project to one active sprint,
        # so a project that allows several leaves it empty.
        for sprint in self:
            sprint.active_project_id = (
                sprint.project_id
                if sprint.state == "in_progress"
                and not sprint.project_id.allow_multiple_active_sprints
                else False
            )

    @api.depends("task_ids")
    def _compute_tasks_count(self):
        tasks_count_by_sprint = dict(
            self.env["project.task"]._read_group(
                [("sprint_id", "in", self.ids)], ["sprint_id"], ["__count"]
            )
        )
        for sprint in self:
            sprint.tasks_count = tasks_count_by_sprint.get(sprint, 0)

    @api.constrains("project_id")
    def _check_project_scrum_enabled(self):
        if any(not sprint.project_id.use_scrum for sprint in self):
            raise ValidationError(
                self.env._("Sprints can only be created in projects with Scrum enabled.")
            )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("state", "draft") != "draft":
                raise ValidationError(self.env._("New sprints must start as planned."))
            self._check_project_manager_role(
                project=self.env["project.project"].browse(vals.get("project_id"))
            )
        return super().create(vals_list)

    def _commit_current_scope(self, revision_reason=None):
        self.ensure_one()
        self._check_project_manager_role()
        tasks = self.task_ids
        super(ProjectSprint, self).write(
            {
                "planning_confirmed": True,
                "committed_task_count": len(tasks),
                "completed_task_count": 0,
            }
        )
        actor_id = self.env.uid
        commitment_model = self.env["project.sprint.commitment"].sudo().with_context(
            allow_sprint_snapshot_write=True
        )
        commitment_model.create(
            {
                "sprint_id": self.id,
                "revision": self.env["project.sprint.commitment"].search_count(
                    [("sprint_id", "=", self.id)]
                )
                + 1,
                "reason": revision_reason or self.env._("Initial plan"),
                "task_count": len(tasks),
                "user_id": actor_id,
            }
        )
        commitment = commitment_model.search(
            [("sprint_id", "=", self.id)], order="revision desc, id desc", limit=1
        )
        self.env["project.sprint.commitment.line"].sudo().with_context(
            allow_sprint_snapshot_write=True
        ).create(
            [
                {
                    "commitment_id": commitment.id,
                    "task_id": task.id,
                    "issue_key": getattr(task, "issue_key", False) or task.display_name,
                    "task_name": task.name,
                    "estimated_snapshot": task._scrum_estimate()[0],
                    "story_points_snapshot": task._scrum_estimate()[1],
                    "has_sprint_children": bool(task.child_ids & tasks),
                    "user_ids": [(6, 0, task.user_ids.ids)],
                }
                for task in tasks
            ]
        )
        self.env["project.sprint.commitment.capacity"].sudo().with_context(
            allow_sprint_snapshot_write=True
        ).create(
            [
                {
                    "commitment_id": commitment.id,
                    "user_id": line.user_id.id,
                    "user_name": line.user_id.name,
                    "capacity_points": line.capacity_points,
                }
                for line in self.capacity_ids
            ]
        )
        return tasks

    def write(self, vals):
        self._check_project_manager_role()
        managed_fields = {
            "planning_confirmed",
            "committed_task_count",
            "completed_task_count",
            "committed_points_at_close",
            "completed_points",
            "scope_change_ids",
            "commitment_ids",
            "close_summary",
        }
        if managed_fields.intersection(vals):
            raise UserError(
                self.env._("Sprint snapshots and summaries are system managed.")
            )
        planning_fields = {
            "name",
            "user_ids",
            "description",
            "project_id",
            "date_start",
            "date_option",
            "date_end",
        }
        if planning_fields.intersection(vals):
            if any(sprint.state != "draft" for sprint in self):
                raise UserError(
                    self.env._("Sprint planning details are locked after the sprint starts.")
                )
        target_state = vals.get("state")
        if target_state:
            if target_state == "in_progress":
                # Serialize concurrent starts before checking the active sprint.
                # The partial unique index remains the final database invariant.
                for project_id in sorted(self.mapped("project_id").ids):
                    self.env.cr.execute(
                        "SELECT pg_advisory_xact_lock(%s, %s)",
                        (1095190872, project_id),
                    )
                self.invalidate_recordset(
                    ["state", "active_project_id", "planning_confirmed"]
                )
            expected_next = {"draft": "in_progress", "in_progress": "done"}
            for sprint in self:
                # A manager can reopen a completed sprint through agile_reopen, which sets this context.
                reopening = (
                    self.env.context.get("agile_reopen_sprint")
                    and sprint.state == "done"
                    and target_state == "in_progress"
                )
                if (
                    target_state != sprint.state
                    and expected_next.get(sprint.state) != target_state
                    and not reopening
                ):
                    raise UserError(
                        self.env._("A sprint can only move from planned to active to completed.")
                    )
                if sprint.state == "draft" and target_state == "in_progress":
                    another_active = not sprint.project_id.allow_multiple_active_sprints and self.search(
                        [
                            ("project_id", "=", sprint.project_id.id),
                            ("state", "=", "in_progress"),
                            ("id", "!=", sprint.id),
                        ],
                        limit=1,
                    )
                    if another_active:
                        raise UserError(
                            self.env._("This project already has an active sprint.")
                        )
                    if not sprint.planning_confirmed:
                        raise UserError(
                            self.env._("Confirm the sprint plan before starting it.")
                        )
                    if sprint._is_confirmed_plan_stale():
                        raise UserError(
                            self.env._(
                                "This confirmed plan has changed. Update the plan with a reason before starting."
                            )
                        )
                if sprint.state == "in_progress" and target_state == "done":
                    open_tasks = sprint.task_ids.filtered(
                        lambda task: task.state not in ("1_done", "1_canceled")
                    )
                    if open_tasks:
                        raise UserError(
                            self.env._(
                                "Move each unfinished issue to the backlog or another "
                                "planned sprint before completing this sprint."
                            )
                        )
                    vals = dict(vals)
                    done_tasks = sprint.task_ids.filtered(
                        lambda task: task.state == "1_done"
                    )
                    committed_lines = sprint.commitment_ids.sorted(
                        "revision", reverse=True
                    )[:1].line_ids
                    committed_points = sum(
                        line.story_points_snapshot
                        for line in committed_lines
                        if not line.has_sprint_children
                        and line.estimated_snapshot
                        and (
                            not line.task_id
                            or line.task_id.state != "1_canceled"
                        )
                    )
                    completed_points = sum(
                        line.story_points_snapshot
                        for line in committed_lines
                        if not line.has_sprint_children
                        and line.estimated_snapshot
                        and line.task_id in done_tasks
                    )
                    vals.update(
                        close_summary=self.env._(
                            "Completed %(done)s of %(committed)s planned issues "
                            "(%(completed_points)s of %(committed_points)s points). "
                            "Canceled issues are excluded from point totals.",
                            done=len(done_tasks),
                            committed=sprint.committed_task_count,
                            completed_points=completed_points,
                            committed_points=committed_points,
                        ),
                        completed_task_count=len(done_tasks),
                        completed_points=completed_points,
                        committed_points_at_close=committed_points,
                    )
        if "project_id" in vals:
            for sprint in self:
                if sprint.state != "draft" or sprint.task_ids:
                    raise UserError(
                        self.env._("A sprint's project cannot change after planning begins.")
                    )
        if target_state == "in_progress":
            try:
                with self.env.cr.savepoint():
                    return super().write(vals)
            except IntegrityError as error:
                raise UserError(
                    self.env._("This project already has an active sprint.")
                ) from error
        return super().write(vals)

    def action_start(self):
        self.ensure_one()
        self._check_project_manager_role()
        if not self.planning_confirmed:
            raise UserError(self.env._("Confirm the sprint plan before starting it."))
        if self._is_confirmed_plan_stale():
            raise UserError(
                self.env._(
                    "This confirmed plan has changed. Update the plan with a reason before starting."
                )
            )
        self.write({"state": "in_progress"})

    def action_confirm_plan(self):
        self.ensure_one()
        self._check_project_manager_role()
        if self.state != "draft":
            raise UserError(self.env._("Only a planned sprint can be confirmed."))
        tasks = self._commit_current_scope()
        self.action_log_initial_scope(tasks)
        self.message_post(
            body=self.env._(
                "Sprint plan confirmed: %(count)s issues.",
                count=len(tasks),
            )
        )

    def action_log_initial_scope(self, tasks):
        self.ensure_one()
        self._record_scope_changes(tasks, "add", self.env._("Initial confirmed plan"))

    def _record_scope_changes(self, tasks, operation, reason=None):
        self._check_project_manager_role()
        actor_id = self.env.uid
        change_model = self.env["project.sprint.scope.change"].sudo().with_context(
            allow_sprint_snapshot_write=True
        )
        for task in tasks:
            change_model.create(
                {
                    "sprint_id": self.id,
                    "task_id": task.id,
                    "operation": operation,
                    "reason": reason or "",
                    "task_name": task.name,
                    "user_id": actor_id,
                }
            )

    def action_refresh_commitment(self, reason):
        self.ensure_one()
        self._check_project_manager_role()
        if self.state != "draft" or not self.planning_confirmed:
            raise UserError(
                self.env._("Only a confirmed planned sprint can be replanned.")
            )
        if not reason or not reason.strip():
            raise ValidationError(self.env._("Enter a reason for the scope change."))
        current_tasks = self.task_ids
        previous_commitment = self.commitment_ids.sorted("revision", reverse=True)[:1]
        initial_task_ids = set(previous_commitment.line_ids.mapped("task_id").ids)
        current_task_ids = set(current_tasks.ids)
        added = self.env["project.task"].browse(current_task_ids - initial_task_ids)
        removed = self.env["project.task"].browse(initial_task_ids - current_task_ids)
        self._record_scope_changes(added, "add", reason.strip())
        self._record_scope_changes(removed, "remove", reason.strip())
        self._commit_current_scope(revision_reason=reason.strip())
        self.message_post(
            body=self.env._(
                "Sprint scope updated by %(user)s: %(added)s added, "
                "%(removed)s removed. Reason: %(reason)s",
                user=self.env.user.name,
                added=len(added),
                removed=len(removed),
                reason=reason.strip(),
            )
        )

    def action_open_scope_change(self):
        self.ensure_one()
        self._check_project_manager_role()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Update Sprint Plan"),
            "res_model": "project.sprint.scope.change.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_sprint_id": self.id},
        }

    def action_open_correction(self):
        self.ensure_one()
        self._check_project_manager_role()
        if self.state != "done":
            raise UserError(
                self.env._("Corrections are available only for completed sprints.")
            )
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Correct Completed Sprint"),
            "res_model": "project.sprint.correction.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_sprint_id": self.id},
        }

    def unlink(self):
        self._check_project_manager_role()
        if any(
            sprint.state != "draft"
            or sprint.planning_confirmed
            or sprint.task_ids
            or sprint.commitment_ids
            or sprint.correction_ids
            for sprint in self
        ):
            raise UserError(
                self.env._(
                    "A sprint with issues or history cannot be deleted. Keep it for reporting."
                )
            )
        return super().unlink()

    def action_done(self):
        self.ensure_one()
        self._check_project_manager_role()
        if self.state == "done":
            return True
        if self.state != "in_progress":
            raise UserError(
                self.env._("Only an active sprint can be completed.")
            )
        if any(not sprint.planning_confirmed for sprint in self):
            raise UserError(
                self.env._("Confirm the sprint plan before starting it.")
            )
        self.write({"state": "done"})

    def action_tasks(self):
        self.ensure_one()
        return {
            "name": self.env._("Issues"),
            "type": "ir.actions.act_window",
            "res_model": "project.task",
            "view_mode": "list,form,kanban",
            "domain": [("sprint_id", "=", self.id)],
            "context": {
                "default_project_id": self.project_id.id,
                "default_sprint_id": self.id,
            },
        }

    @api.depends("date_start", "date_option")
    def _compute_date_end(self):
        for record in self:
            if record.date_option != "custom":
                num, interval = record.date_option.split("_")
                record.date_end = record.date_start + relativedelta(
                    **{interval: int(num)}
                )
            else:
                record.date_end = record.date_start + relativedelta(days=1)


class ProjectSprintScopeChange(models.Model):
    _name = "project.sprint.scope.change"
    _description = "Project Sprint Scope Change"
    _order = "create_date desc, id desc"

    sprint_id = fields.Many2one(
        "project.sprint", required=True, ondelete="cascade", index=True
    )
    task_id = fields.Many2one("project.task", ondelete="set null", index=True)
    task_name = fields.Char(required=True)
    operation = fields.Selection(
        [("add", "Added"), ("remove", "Removed")], required=True
    )
    reason = fields.Text(required=True)
    user_id = fields.Many2one("res.users", required=True, ondelete="restrict")
    create_date = fields.Datetime(readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("allow_sprint_snapshot_write"):
            raise UserError(self.env._("Sprint scope history is system managed."))
        return super().create(vals_list)

    def write(self, vals):
        raise UserError(self.env._("Sprint scope history cannot be edited."))

    def unlink(self):
        if self.env.context.get("module_uninstall"):
            return super().unlink()
        raise UserError(self.env._("Sprint scope history cannot be deleted."))


class ProjectSprintCommitment(models.Model):
    _name = "project.sprint.commitment"
    _description = "Project Sprint Commitment Snapshot"
    _order = "revision desc, id desc"
    _task_commitment_revision_unique = models.Constraint(
        "UNIQUE(sprint_id, revision)",
        "A sprint plan revision number must be unique.",
    )

    sprint_id = fields.Many2one(
        "project.sprint", required=True, ondelete="cascade", index=True
    )
    revision = fields.Integer(required=True, readonly=True)
    reason = fields.Text(required=True, readonly=True)
    line_ids = fields.One2many(
        "project.sprint.commitment.line", "commitment_id", readonly=True
    )
    capacity_line_ids = fields.One2many(
        "project.sprint.commitment.capacity", "commitment_id", readonly=True
    )
    task_count = fields.Integer(readonly=True)
    user_id = fields.Many2one("res.users", required=True, readonly=True)
    create_date = fields.Datetime(readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("allow_sprint_snapshot_write"):
            raise UserError(self.env._("Sprint commitment is system managed."))
        return super().create(vals_list)

    def write(self, vals):
        raise UserError(self.env._("Sprint commitment history cannot be edited."))

    def unlink(self):
        if self.env.context.get("module_uninstall"):
            return super().unlink()
        raise UserError(self.env._("Sprint commitment history cannot be deleted."))


class ProjectSprintCommitmentLine(models.Model):
    _name = "project.sprint.commitment.line"
    _description = "Committed Issue Snapshot"
    _order = "id"

    commitment_id = fields.Many2one(
        "project.sprint.commitment", required=True, ondelete="cascade", index=True
    )
    task_id = fields.Many2one("project.task", ondelete="set null", readonly=True)
    issue_key = fields.Char(required=True, readonly=True)
    task_name = fields.Char(required=True, readonly=True)
    estimated_snapshot = fields.Boolean(readonly=True)
    story_points_snapshot = fields.Float(digits=(16, 2), readonly=True)
    has_sprint_children = fields.Boolean(readonly=True)
    user_ids = fields.Many2many(
        "res.users",
        "project_sprint_commitment_user_rel",
        "commitment_line_id",
        "user_id",
        string="Assignees at confirmation",
        readonly=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("allow_sprint_snapshot_write"):
            raise UserError(self.env._("Sprint commitment is system managed."))
        return super().create(vals_list)

    def write(self, vals):
        raise UserError(self.env._("Sprint commitment history cannot be edited."))

    def unlink(self):
        if self.env.context.get("module_uninstall"):
            return super().unlink()
        raise UserError(self.env._("Sprint commitment history cannot be deleted."))


class ProjectSprintCommitmentCapacity(models.Model):
    _name = "project.sprint.commitment.capacity"
    _description = "Committed Sprint Member Capacity"
    _order = "id"

    commitment_id = fields.Many2one(
        "project.sprint.commitment", required=True, ondelete="cascade", index=True
    )
    user_id = fields.Many2one("res.users", ondelete="set null", readonly=True)
    user_name = fields.Char(required=True, readonly=True)
    capacity_points = fields.Float(
        required=True, default=0, digits=(16, 2), readonly=True
    )

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("allow_sprint_snapshot_write"):
            raise UserError(self.env._("Sprint capacity history is system managed."))
        return super().create(vals_list)

    def write(self, vals):
        raise UserError(self.env._("Sprint capacity history cannot be edited."))

    def unlink(self):
        if self.env.context.get("module_uninstall"):
            return super().unlink()
        raise UserError(self.env._("Sprint capacity history cannot be deleted."))
