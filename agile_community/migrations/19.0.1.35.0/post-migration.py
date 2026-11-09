from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Default workflows made before W-202 get today's required fields."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    env["project.project"]._agile_backfill_default_required_fields()
