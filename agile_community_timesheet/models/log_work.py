from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AgileLogWork(models.TransientModel):
    _name = "agile.log.work"
    _description = "Log work on an Agile issue"

    task_id = fields.Many2one("project.task", required=True, readonly=True, ondelete="cascade")
    hours = fields.Float(string="Time spent", required=True, help="Hours and minutes, for example 1:30.")
    date = fields.Date(string="Date", required=True, default=fields.Date.context_today)
    description = fields.Char(string="What did you do?")

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        task = self.env["project.task"].browse(self.env.context.get("default_task_id") or values.get("task_id"))
        if task:
            task._agile_check_can_log_work()
        return values

    def action_log_work(self):
        self.ensure_one()
        task = self.task_id
        task._agile_check_can_log_work()
        if self.hours <= 0:
            raise UserError(_("Enter the time you spent, more than zero."))
        employee = self.env.user.employee_id
        self.env["account.analytic.line"].create({
            "name": self.description or "/",
            "task_id": task.id,
            "project_id": task.project_id.id,
            "employee_id": employee.id,
            "date": self.date,
            "unit_amount": self.hours,
        })
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "message": _("Logged %(time)s on %(key)s.", time=self._hours_text(), key=task.issue_key or task.name),
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    def _hours_text(self):
        minutes = round(self.hours * 60)
        return "%d:%02d" % divmod(minutes, 60)
