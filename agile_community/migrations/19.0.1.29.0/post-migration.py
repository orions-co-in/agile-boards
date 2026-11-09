from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Enforce native Project visibility for project-scoped Agile roles."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    Member = env["agile.project.member"].sudo().with_context(agile_role_seed=True)
    members = Member.search([
        ("project_id.agile_enabled", "=", True),
    ])
    inaccessible = members.filtered(
        lambda member: not member.user_id.active
        or not member.project_id.with_user(member.user_id).has_access("read")
    )
    inaccessible.unlink()

    projects = env["project.project"].with_context(active_test=False).search(
        [("agile_enabled", "=", True)]
    )
    projects._initialize_agile_team_roles()
