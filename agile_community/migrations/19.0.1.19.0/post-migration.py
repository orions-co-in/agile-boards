from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    projects = env["project.project"].search([("agile_enabled", "=", True)])
    projects._initialize_agile_team_roles()
