from odoo import _, fields, models


class AgileSprintReopen(models.TransientModel):
    _name = "agile.sprint.reopen"
    _description = "Reopen a completed sprint"

    sprint_id = fields.Many2one("project.sprint", required=True, readonly=True)
    name = fields.Char(related="sprint_id.name", readonly=True)
    reason = fields.Text(required=True, help="Kept in the project audit and on the sprint.")

    def action_reopen(self):
        self.ensure_one()
        self.sprint_id.agile_reopen(self.reason)
        return {"type": "ir.actions.act_window_close"}
