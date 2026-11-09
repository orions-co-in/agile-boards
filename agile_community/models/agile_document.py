"""Links to documents (S-1131): an issue keeps titled links to web pages or Odoo pages such as Knowledge articles."""
import re

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

MAX_DOCUMENTS = 50
URL_LIMIT = 2000
WEB_URL = re.compile(r"^https?://[^\s/$.?#][^\s]*$", re.IGNORECASE)
ODOO_URL = re.compile(r"^/odoo/[^\s]*$")


class AgileIssueDocument(models.Model):
    _name = "agile.issue.document"
    _description = "Agile Issue Document Link"
    _order = "sequence, id"

    task_id = fields.Many2one("project.task", required=True, index=True, ondelete="cascade")
    title = fields.Char(required=True)
    url = fields.Char(string="Link", required=True, help="A web address (https://...) or an Odoo page such as /odoo/knowledge/3.")
    kind = fields.Selection(
        [("web", "Web page"), ("odoo", "Odoo page")], compute="_compute_kind", string="Type",
    )
    sequence = fields.Integer(default=10)

    @api.depends("url")
    def _compute_kind(self):
        for document in self:
            document.kind = "odoo" if (document.url or "").startswith("/odoo/") else "web"

    @api.constrains("url", "title")
    def _check_link(self):
        for document in self:
            url = (document.url or "").strip()
            if len(url) > URL_LIMIT or not (WEB_URL.match(url) or ODOO_URL.match(url)):
                raise ValidationError(
                    _("A link must start with http:// or https:// (or /odoo/ for a page in this database), have no spaces and be at most %(limit)s characters.", limit=URL_LIMIT)
                )
            if not (document.title or "").strip():
                raise ValidationError(_("Give the link a title."))

    @api.constrains("task_id")
    def _check_limit(self):
        for task in self.task_id:
            if len(task.sudo().agile_document_ids) > MAX_DOCUMENTS:
                raise ValidationError(_("An issue can have at most %(limit)s document links.", limit=MAX_DOCUMENTS))

    def _check_can_edit(self, tasks):
        if self.env.su:
            return
        for task in tasks:
            if task.project_id._agile_role_for_user(self.env.user) not in ("manager", "contributor"):
                raise AccessError(_("Only Agile managers and contributors can change document links."))

    @api.model_create_multi
    def create(self, vals_list):
        self._check_can_edit(self.env["project.task"].browse([v["task_id"] for v in vals_list if v.get("task_id")]))
        return super().create(vals_list)

    def write(self, vals):
        self._check_can_edit(self.task_id | self.env["project.task"].browse(vals.get("task_id")))
        return super().write(vals)

    def unlink(self):
        self._check_can_edit(self.task_id)
        return super().unlink()


class ProjectTask(models.Model):
    _inherit = "project.task"

    agile_document_ids = fields.One2many("agile.issue.document", "task_id", string="Documents", copy=True)
    agile_document_count = fields.Integer(compute="_compute_agile_document_count")

    @api.depends("agile_document_ids")
    def _compute_agile_document_count(self):
        for task in self:
            task.agile_document_count = len(task.agile_document_ids)
