from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Jira-style board: the Ready column is named To Do, and issues planned into a sprint start there."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    stages = env["project.task.type"].with_context(active_test=False).search([
        ("agile_status", "=", "ready"),
        ("name", "=", "Ready"),
    ])
    stages.write({"name": "To Do"})
    tasks = env["project.task"].with_context(active_test=False).search([
        ("agile_issue", "=", True),
        ("agile_is_epic", "=", False),
        ("sprint_id", "!=", False),
        ("sprint_id.state", "!=", "done"),
        ("stage_id.agile_status", "=", "backlog"),
    ])
    tasks._agile_follow_sprint("ready")
