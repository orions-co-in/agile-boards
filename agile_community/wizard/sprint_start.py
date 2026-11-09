from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AgileSprintStartWizard(models.TransientModel):
    """Start sprint dialog (NU-05): name, dates and goal, with warnings before the sprint starts."""

    _name = "agile.sprint.start.wizard"
    _description = "Start sprint"

    sprint_id = fields.Many2one("project.sprint", required=True, readonly=True, ondelete="cascade")
    name = fields.Char(required=True)
    date_start = fields.Date(string="Start date", required=True)
    date_end = fields.Date(string="End date", required=True)
    goal = fields.Text(string="Sprint goal")
    warning = fields.Text(compute="_compute_warning")

    @api.depends("sprint_id", "date_start", "date_end")
    def _compute_warning(self):
        today = fields.Date.context_today(self)
        for wizard in self:
            lines = []
            sprint = wizard.sprint_id
            if wizard.date_start and wizard.date_start > today:
                lines.append(_(
                    "The planned start (%(date)s) is in the future. The sprint will start today and its dates will be kept as set here.",
                    date=wizard.date_start,
                ))
            if wizard.date_start and wizard.date_end and wizard.date_end < wizard.date_start:
                lines.append(_("The end date is before the start date."))
            if sprint and sprint.capacity_points and sprint.planned_points > sprint.capacity_points:
                lines.append(_(
                    "Planned points (%(planned)s) exceed the team's capacity (%(capacity)s). You may still start.",
                    planned=sprint.planned_points, capacity=sprint.capacity_points,
                ))
            wizard.warning = "\n".join(lines) or False

    def action_start_sprint(self):
        self.ensure_one()
        if self.date_end < self.date_start:
            raise UserError(_("The end date cannot be before the start date."))
        sprint = self.sprint_id
        sprint.write({
            "name": self.name,
            "date_option": "custom",
            "date_start": self.date_start,
            "date_end": self.date_end,
            "description": self.goal,
        })
        sprint.action_start()
        return {"type": "ir.actions.act_window_close"}
