from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Make the member company boundary global, not a broad manager grant."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    rule = env.ref(
        "agile_community.agile_project_member_company_rule",
        raise_if_not_found=False,
    )
    if rule and rule.groups:
        rule.write({"groups": [(5, 0, 0)]})
