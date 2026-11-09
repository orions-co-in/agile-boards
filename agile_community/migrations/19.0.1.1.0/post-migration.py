from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    projects = env["project.project"].with_context(
        active_test=False,
        agile_workflow_setup=True,
    ).search([("agile_enabled", "=", True)])
    projects._ensure_agile_workflow_stages()
