from odoo import _
from odoo.addons.web.controllers.action import Action
from odoo.exceptions import AccessError
from odoo.http import request, route


class AgileAction(Action):
    @route()
    def load(self, action_id, context=None):
        actions = request.env["ir.actions.actions"].sudo()
        if isinstance(action_id, int) or str(action_id).isdigit():
            action = actions.browse(int(action_id)).exists()
        elif "." in action_id:
            action = request.env.ref(action_id, raise_if_not_found=False)
        else:
            action = actions.search([("path", "=", action_id)], limit=1)

        review_action = request.env.ref(
            "agile_community.action_agile_my_work_review"
        )
        result = super().load(action_id, context=context)
        if action and action.id == review_action.id:
            project_ids = request.env[
                "agile.project.member"
            ]._readable_project_ids_for_roles(["reviewer", "manager"])
            if not project_ids:
                raise AccessError(
                    _("Only project reviewers and managers can open this review queue.")
                )
            result["domain"] = [
                ("project_id.agile_enabled", "=", True),
                ("agile_issue", "=", True),
                ("stage_id.agile_status", "=", "review"),
                ("project_id", "in", project_ids),
            ]
        return result
