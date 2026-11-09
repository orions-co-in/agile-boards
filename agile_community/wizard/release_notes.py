from odoo import api, fields, models


class AgileReleaseNotesWizard(models.TransientModel):
    _name = "agile_community.release_notes_wizard"
    _description = "Agile Release Notes"

    release_id = fields.Many2one("project.version", required=True, readonly=True)
    notes = fields.Text(compute="_compute_notes", readonly=True)

    @api.depends("release_id")
    def _compute_notes(self):
        for wizard in self:
            wizard.notes = (
                wizard.release_id._release_notes_markdown() if wizard.release_id else False
            )
