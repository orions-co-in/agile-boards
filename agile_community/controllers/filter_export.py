from odoo import http
from odoo.exceptions import AccessError, UserError
from odoo.http import request


class AgileFilterExport(http.Controller):
    @http.route("/agile/filter/<int:filter_id>/export", type="http", auth="user")
    def export(self, filter_id, **_kwargs):
        """The filter's issues as CSV, read with the signed-in person's own rights."""
        record = request.env["agile.filter"].browse(filter_id).exists()
        try:
            record.check_access("read")
            record.project_id._check_agile_backlog_access()
            content = record._export_csv()
        except (AccessError, UserError):
            raise request.not_found() from None
        name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in record.name).strip() or "filter"
        return request.make_response(content, headers=[
            ("Content-Type", "text/csv; charset=utf-8"),
            ("Content-Disposition", f'attachment; filename="{name}.csv"'),
        ])
