import base64
import json

from odoo import _, api, fields, models
from odoo.exceptions import UserError

MAX_FILE_BYTES = 1_000_000


class AgileWorkflowTemplateWizard(models.TransientModel):
    _name = "agile_community.workflow_template_wizard"
    _description = "Share an Agile workflow"

    workflow_id = fields.Many2one("agile.workflow", string="Workflow", ondelete="cascade")
    source_project_id = fields.Many2one("project.project", readonly=True, ondelete="cascade")
    project_id = fields.Many2one(
        "project.project", string="Copy into project", ondelete="cascade",
        domain="[('agile_enabled', '=', True)]",
    )
    file = fields.Binary(string="Workflow file")
    filename = fields.Char()
    new_workflow_id = fields.Many2one("agile.workflow", readonly=True, ondelete="set null")
    report = fields.Text(readonly=True)

    def _finish(self, workflow, notes):
        lines = [_("Created the workflow %(name)s in %(project)s.", name=workflow.name, project=workflow.project_id.name)]
        lines += notes or [_("Everything in the file was used.")]
        self.write({"new_workflow_id": workflow.id, "report": "\n".join(lines)})
        return self._reopen()

    def _reopen(self):
        return {
            "type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id,
            "view_mode": "form", "target": "new",
        }

    def action_download(self):
        self.ensure_one()
        if not self.workflow_id:
            raise UserError(_("Open this from a workflow to download it."))
        self.workflow_id.agile_template_data()  # checks the person manages it
        return {"type": "ir.actions.act_url", "url": "/agile/workflow/%d/template" % self.workflow_id.id, "target": "self"}

    def action_copy(self):
        self.ensure_one()
        if not self.workflow_id or not self.project_id:
            raise UserError(_("Choose the project to copy this workflow into."))
        workflow, notes = self.workflow_id.agile_copy_to_project(self.project_id)
        return self._finish(workflow, notes)

    def action_import(self):
        self.ensure_one()
        if not self.file or not self.project_id:
            raise UserError(_("Choose a workflow file and a project."))
        raw = base64.b64decode(self.file)
        if len(raw) > MAX_FILE_BYTES:
            raise UserError(_("This file is too large to be a workflow."))
        try:
            data = json.loads(raw.decode("utf-8"))
        except ValueError:
            raise UserError(_("This file is not an Agile workflow.")) from None
        workflow, notes = self.env["agile.workflow"].agile_create_from_template(self.project_id, data)
        return self._finish(workflow, notes)

    def action_open_workflow(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "res_model": "agile.workflow", "res_id": self.new_workflow_id.id,
            "view_mode": "form", "target": "current",
        }
