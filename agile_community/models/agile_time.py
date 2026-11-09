from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class ProjectTask(models.Model):
    _inherit = "project.task"

    # The original estimate is the task's own Allocated Time (hours), so it is the same figure the
    # Timesheets app already shows. Time logged is typed in here, or read from timesheets by the bridge.
    agile_logged_hours = fields.Float(
        string="Time logged", copy=False, tracking=True,
        help="Hours worked so far. With the Timesheets app it is the sum of the issue's timesheets.",
    )
    agile_remaining_hours = fields.Float(
        string="Remaining estimate", compute="_compute_agile_remaining_hours", store=True, readonly=False,
        copy=False, tracking=True,
        help="Hours left. It follows the original estimate minus the time logged until you type a figure.",
    )
    agile_time_progress = fields.Float(
        string="Time progress", compute="_compute_agile_time_progress",
        help="Time logged as a share of the original estimate (shown as a percentage; over 100% is over estimate).",
    )

    @api.depends("allocated_hours", "agile_logged_hours")
    def _compute_agile_remaining_hours(self):
        for task in self:
            task.agile_remaining_hours = max(task.allocated_hours - task.agile_logged_hours, 0.0)

    @api.depends("allocated_hours", "agile_logged_hours")
    def _compute_agile_time_progress(self):
        for task in self:
            task.agile_time_progress = (
                task.agile_logged_hours / task.allocated_hours if task.allocated_hours else 0.0
            )

    @api.constrains("allocated_hours", "agile_logged_hours", "agile_remaining_hours")
    def _check_agile_time_not_negative(self):
        for task in self:
            if min(task.allocated_hours, task.agile_logged_hours, task.agile_remaining_hours) < 0:
                raise ValidationError(_("Estimates and logged time cannot be negative."))

    agile_log_time_available = fields.Boolean(
        compute="_compute_agile_log_time_available",
        help="True when the issue can be logged against without the Timesheets app.",
    )
    agile_can_assign_me = fields.Boolean(compute="_compute_agile_can_assign_me")

    @api.depends("agile_issue", "project_id")
    @api.depends_context("uid")
    def _compute_agile_log_time_available(self):
        for task in self:
            task.agile_log_time_available = bool(
                task.id and task.agile_issue and not task.agile_is_epic and not task._agile_worklog_available()
                and task.project_id._agile_role_for_user() in ("manager", "contributor")
            )

    @api.depends("agile_issue", "project_id", "user_ids")
    @api.depends_context("uid")
    def _compute_agile_can_assign_me(self):
        for task in self:
            task.agile_can_assign_me = bool(
                task.id and task.agile_issue and self.env.user not in task.user_ids
                and task.project_id._agile_role_for_user() in ("manager", "contributor")
            )

    def _agile_check_can_log_time(self):
        self.ensure_one()
        if not self.agile_log_time_available:
            raise UserError(_("Only Agile managers and contributors can log work on an issue."))

    def action_agile_log_time(self):
        self.ensure_one()
        self._agile_check_can_log_time()
        return {
            "type": "ir.actions.act_window",
            "name": _("Log work"),
            "res_model": "agile.log.time",
            "view_mode": "form",
            "target": "new",
            "context": {"default_task_id": self.id},
        }

    def action_agile_assign_to_me(self):
        for task in self:
            if not task.agile_can_assign_me:
                raise UserError(_("Only Agile managers and contributors can assign an issue to themselves."))
            task.write({"user_ids": [(4, self.env.user.id)]})
        return True
