from odoo import fields, models


class ProjectSprintScopeChangeWizard(models.TransientModel):
    _name = "project.sprint.scope.change.wizard"
    _description = "Replan Project Sprint"

    sprint_id = fields.Many2one("project.sprint", required=True, readonly=True)
    reason = fields.Text(required=True)

    def action_apply(self):
        self.ensure_one()
        self.sprint_id.action_refresh_commitment(self.reason)
        return {"type": "ir.actions.act_window_close"}
