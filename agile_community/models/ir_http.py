from odoo import models
from odoo.http import request

RAW_BODY_PATHS = ("/agile/chat/slack/",)


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    @classmethod
    def _pre_dispatch(cls, rule, args):
        # Slack signs the raw form body. Odoo parses the form before the route runs and that consumes the
        # stream, so the body is read (and cached) first on these routes only.
        if request.httprequest.path.startswith(RAW_BODY_PATHS):
            request.httprequest.get_data()
        return super()._pre_dispatch(rule, args)
