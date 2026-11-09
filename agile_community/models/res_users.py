from odoo import fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    # Set on the user an AI agent signs in as; the agent connector itself is in agile_pro.
    agile_is_agent = fields.Boolean(string="AI agent", default=False, copy=False)
