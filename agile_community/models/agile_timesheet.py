from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

TIMESHEET_GROUP = "hr_timesheet.group_hr_timesheet_user"


class ProjectTask(models.Model):
    """Timesheet link. It only does anything when the Timesheets app (hr_timesheet) is installed:
    every hook below checks that the task has hr_timesheet's fields, so Agile Boards does not depend on it."""

    _inherit = "project.task"

    # Without Timesheets this stays the typed figure; with it, the timesheets say what was logged.
    agile_logged_hours = fields.Float(
        compute="_compute_agile_logged_hours", store=True, readonly=False, compute_sudo=True)
    agile_log_work_available = fields.Boolean(compute="_compute_agile_log_work_available")

    def _agile_has_timesheets(self):
        return "effective_hours" in self._fields

    def _register_hook(self):
        super()._register_hook()
        if self._agile_has_timesheets():
            # The figure is read from the timesheets, so nobody types it.
            self._fields["agile_logged_hours"].readonly = True

    @api.depends(lambda model: ("effective_hours",) if "effective_hours" in model._fields else ())
    def _compute_agile_logged_hours(self):
        has = self._agile_has_timesheets()
        for task in self:
            task.agile_logged_hours = task.effective_hours if has else 0.0

    @api.depends(lambda model: ("agile_issue", "project_id") + (
        ("project_id.allow_timesheets",) if "effective_hours" in model._fields else ()))
    def _compute_agile_log_work_available(self):
        has = self._agile_has_timesheets()
        for task in self:
            task.agile_log_work_available = bool(
                has and task.id and task.agile_issue and task.project_id.allow_timesheets)

    def _agile_worklog_available(self):
        return self._agile_has_timesheets()

    def _agile_worklog_entries(self):
        self.ensure_one()
        if not self._agile_has_timesheets():
            return []
        # Read as the person, so timesheets they may not see stay out of the feed.
        lines = self.env["account.analytic.line"]
        if lines.has_access("read"):
            # People and agents without Timesheets rights (an agent is not a timesheet user) see no work entries.
            lines = lines.search([("task_id", "=", self.id)], order="date desc, id desc", limit=200)
        return [
            {
                "key": "w%s" % line.id,
                "kind": "worklog",
                "date": fields.Datetime.to_string(line.create_date or fields.Datetime.now()),
                "author": line.employee_id.name or line.user_id.name or "",
                "text": line.name or "",
                "changes": [],
                "hours": line.unit_amount,
                "work_date": fields.Date.to_string(line.date),
                "note": False,
            }
            for line in lines
        ]

    def _agile_check_can_log_work(self):
        """Time is logged by team members who have an employee and a project that allows timesheets."""
        self.ensure_one()
        if not self._agile_has_timesheets():
            raise UserError(_("Timesheets are not installed."))
        project = self.project_id
        if not self.agile_issue or not project.allow_timesheets:
            raise UserError(_("Timesheets are not turned on for this project."))
        if project._agile_role_for_user() not in ("manager", "contributor"):
            raise AccessError(_("Only Agile managers and contributors can log work."))
        if not self.env.user.has_group(TIMESHEET_GROUP):
            raise AccessError(_("You need Timesheets access to log work."))
        if not self.env.user.employee_id:
            raise UserError(_("Your user has no employee yet, so time cannot be logged. Ask an administrator to link one."))

    def action_agile_log_work(self):
        self.ensure_one()
        self._agile_check_can_log_work()
        return {
            "type": "ir.actions.act_window",
            "name": _("Log work"),
            "res_model": "agile.log.work",
            "view_mode": "form",
            "target": "new",
            "context": {"default_task_id": self.id},
        }
