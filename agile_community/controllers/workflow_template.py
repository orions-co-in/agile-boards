import json

from odoo import http
from odoo.exceptions import AccessError, UserError
from odoo.http import request


class AgileWorkflowTemplate(http.Controller):
    @http.route("/agile/workflow/<int:workflow_id>/template", type="http", auth="user")
    def download(self, workflow_id, **_kwargs):
        """The workflow as a file, for the project's Agile Manager only."""
        workflow = request.env["agile.workflow"].browse(workflow_id).exists()
        if not workflow:
            raise request.not_found()
        try:
            data = workflow.agile_template_data()
        except (AccessError, UserError):
            raise request.not_found() from None
        name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in workflow.name).strip() or "workflow"
        return request.make_response(json.dumps(data, indent=2, ensure_ascii=False), headers=[
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Disposition", f'attachment; filename="{name}.workflow.json"'),
        ])
