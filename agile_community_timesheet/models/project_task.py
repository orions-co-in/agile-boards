from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError


class ProjectTask(models.Model):
    _inherit = "project.task"

    # With the Timesheets app the logged time is what the timesheets say, not a typed figure.
    agile_logged_hours = fields.Float(compute="_compute_agile_logged_hours", store=True, readonly=True, compute_sudo=True)

    @api.depends("effective_hours")
    def _compute_agile_logged_hours(self):
        for task in self:
            task.agile_logged_hours = task.effective_hours

    def _agile_worklog_available(self):
        return True

    def _agile_worklog_entries(self):
        self.ensure_one()
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
        project = self.project_id
        if not self.agile_issue or not project.allow_timesheets:
            raise UserError(_("Timesheets are not turned on for this project."))
        if project._agile_role_for_user() not in ("manager", "contributor"):
            raise AccessError(_("Only Agile managers and contributors can log work."))
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
