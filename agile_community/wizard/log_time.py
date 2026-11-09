from odoo import _, fields, models
from odoo.exceptions import UserError


class AgileLogTimeWizard(models.TransientModel):
    """Log work without the Timesheets app: add the time to the issue and note it in the chatter (NU-22)."""

    _name = "agile.log.time"
    _description = "Log time on an Agile issue"

    task_id = fields.Many2one("project.task", required=True, readonly=True, ondelete="cascade")
    hours = fields.Float(string="Time spent", required=True, help="Hours and minutes, for example 1:30.")
    date = fields.Date(string="Date", required=True, default=fields.Date.context_today)
    description = fields.Char(string="What did you do?")

    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        task = self.env["project.task"].browse(self.env.context.get("default_task_id") or values.get("task_id"))
        if task:
            task._agile_check_can_log_time()
        return values

    def action_log_time(self):
        self.ensure_one()
        task = self.task_id
        task._agile_check_can_log_time()
        if self.hours <= 0:
            raise UserError(_("Enter the time you spent, more than zero."))
        minutes = round(self.hours * 60)
        text = "%d:%02d" % divmod(minutes, 60)
        task.sudo().agile_logged_hours += self.hours
        task.message_post(
            body=_(
                "Logged %(time)s on %(date)s%(note)s.",
                time=text, date=self.date, note=(": " + self.description) if self.description else "",
            ),
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "message": _("Logged %(time)s on %(key)s.", time=text, key=task.issue_key or task.name),
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
