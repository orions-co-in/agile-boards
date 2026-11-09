from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Preserve existing global Agile roles as project-scoped memberships."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    projects = env["project.project"].with_context(active_test=False).search(
        [("agile_enabled", "=", True)]
    )
    projects._initialize_agile_team_roles()
