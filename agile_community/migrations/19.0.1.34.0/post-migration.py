from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Give every Agile project the default workflow that matches today's rules."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    env["project.project"].with_context(active_test=False).search(
        [("agile_enabled", "=", True)]
    )._ensure_agile_default_workflow()
