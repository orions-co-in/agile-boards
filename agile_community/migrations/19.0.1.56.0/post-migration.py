from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """The backlog sits outside the sprint: name the move into a sprint and add the move back."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    transitions = env["agile.workflow.transition"].with_context(active_test=False)
    for transition in transitions.search([("name", "=", "Mark ready")]):
        if (
            transition.from_status_id.category == "backlog"
            and transition.to_status_id.category == "ready"
        ):
            transition.name = "Plan into sprint"
    for workflow in env["agile.workflow"].with_context(active_test=False).search([]):
        statuses = {status.category: status for status in workflow.status_ids}
        if "backlog" not in statuses or "ready" not in statuses:
            continue
        has_back = workflow.transition_ids.filtered(
            lambda t: t.from_status_id == statuses["ready"] and t.to_status_id == statuses["backlog"]
        )
        if not has_back:
            transitions.create({
                "name": "Back to backlog",
                "workflow_id": workflow.id,
                "from_status_id": statuses["ready"].id,
                "to_status_id": statuses["backlog"].id,
                "allow_contributor": False,
                "allow_reviewer": False,
                "allow_manager": True,
            })
