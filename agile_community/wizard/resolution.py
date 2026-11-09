from odoo import api, fields, models

from odoo.addons.agile_community.models.agile_resolution import DEFAULT_RESOLUTION, RESOLUTIONS


class AgileResolutionWizard(models.TransientModel):
    _name = "agile_community.resolution_wizard"
    _description = "Choose why an Agile issue is closed"

    task_id = fields.Many2one("project.task", required=True, ondelete="cascade")
    kind = fields.Selection([("done", "Complete"), ("canceled", "Cancel")], required=True, default="done")
    resolution = fields.Selection(RESOLUTIONS, required=True)

    @api.model
    def default_get(self, fields_list):
        # The dialog opens with the usual answer already chosen.
        values = super().default_get(fields_list)
        values.setdefault("resolution", DEFAULT_RESOLUTION[values.get("kind") or "done"])
        return values

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals.setdefault("resolution", DEFAULT_RESOLUTION[vals.get("kind") or "done"])
        return super().create(vals_list)

    def action_confirm(self):
        self.ensure_one()
        task = self.task_id
        task.write({"agile_resolution": self.resolution})
        # One transaction: when the move is refused, the resolution is rolled back with it.
        return task.action_agile_cancel() if self.kind == "canceled" else task.action_agile_complete()
