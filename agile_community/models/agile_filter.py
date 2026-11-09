import csv
import io
import logging
from datetime import timedelta
from urllib.parse import quote

from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.fields import Domain
from odoo.exceptions import AccessError, UserError, ValidationError

from .agile_query import AgileQuery, QueryError

_logger = logging.getLogger(__name__)
DIGEST_LIMIT = 50
EXPORT_HEAD = ["Key", "Title", "Type", "Status", "Assignee", "Sprint", "Priority", "Story points", "Due date"]


def _safe_cell(value):
    """Spreadsheets run cells that start with these characters as formulas."""
    text = "" if value is False or value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


class AgileFilter(models.Model):
    _name = "agile.filter"
    _description = "Agile Filter"
    _order = "visibility desc, name, id"

    name = fields.Char(required=True)
    project_id = fields.Many2one("project.project", required=True, index=True, ondelete="cascade")
    owner_id = fields.Many2one("res.users", string="Owner", required=True, default=lambda s: s.env.user,
                               ondelete="cascade", index=True)
    visibility = fields.Selection(
        [("private", "Only me"), ("shared", "Everyone on the project")],
        string="Who can see it", required=True, default="private",
    )
    query = fields.Char(
        required=True, default='status = "In Progress"',
    )
    order_by = fields.Selection(
        [("rank", "Rank"), ("priority", "Priority"), ("due", "Due date"), ("updated", "Last updated")],
        string="Sort by", default="rank", required=True,
        help="The order of the exported file and the emailed list.",
    )
    order_direction = fields.Selection(
        [("asc", "Ascending"), ("desc", "Descending")], string="Direction", default="asc", required=True,
    )
    match_count = fields.Integer(string="Matching issues", compute="_compute_match_count")
    subscription_ids = fields.One2many("agile.filter.subscription", "filter_id")
    my_digest = fields.Selection(
        [("none", "Do not email me"), ("daily", "Every day"), ("weekly", "Every week")],
        string="Email me this filter", compute="_compute_my_digest", inverse="_inverse_my_digest",
    )
    my_send_empty = fields.Boolean(
        string="Send even when empty", compute="_compute_my_digest", inverse="_inverse_my_send_empty",
    )
    can_edit = fields.Boolean(compute="_compute_can_edit")

    # ---- helpers ------------------------------------------------------------------

    def _query_tool(self):
        self.ensure_one()
        return AgileQuery(self.env, self.project_id)

    def _issue_domain(self):
        """The filter as a domain for the current user: always the project's own issues."""
        self.ensure_one()
        try:
            domain, _words = self._query_tool().compile(self.query or "")
        except QueryError as error:
            raise UserError(error.message) from None
        return [("project_id", "=", self.project_id.id), ("agile_issue", "=", True)] + domain

    def _issues(self, limit=None):
        self.ensure_one()
        column = {"rank": "sequence", "priority": "priority", "due": "date_deadline", "updated": "write_date"}[self.order_by]
        try:
            written = self._query_tool().order(self.query)
        except QueryError:
            written = ""
        # An ORDER BY in the query wins over the Sort by field.
        order = f"{written or f'{column} {self.order_direction}'}, id"
        return self.env["project.task"].search(self._issue_domain(), limit=limit, order=order)

    @api.depends("query", "project_id")
    @api.depends_context("uid")
    def _compute_match_count(self):
        for record in self:
            try:
                record.match_count = self.env["project.task"].search_count(record._issue_domain())
            except (UserError, AccessError):
                record.match_count = 0

    @api.depends_context("uid")
    @api.depends("subscription_ids.frequency", "subscription_ids.user_id", "subscription_ids.send_empty")
    def _compute_my_digest(self):
        for record in self:
            mine = record.subscription_ids.filtered(lambda s: s.user_id == self.env.user)
            record.my_digest = mine[:1].frequency or "none"
            record.my_send_empty = bool(mine[:1].send_empty)

    def _inverse_my_send_empty(self):
        for record in self:
            record.subscription_ids.sudo().filtered(lambda s: s.user_id == self.env.user).send_empty = record.my_send_empty

    def _inverse_my_digest(self):
        for record in self:
            mine = record.subscription_ids.sudo().filtered(lambda s: s.user_id == self.env.user)
            if record.my_digest in (False, "none"):
                mine.unlink()
            elif mine:
                mine.frequency = record.my_digest
            else:
                self.env["agile.filter.subscription"].sudo().create({
                    "filter_id": record.id, "user_id": self.env.user.id, "frequency": record.my_digest,
                })

    @api.depends_context("uid")
    @api.depends("owner_id", "project_id")
    def _compute_can_edit(self):
        for record in self:
            record.can_edit = record._can_edit()

    def _can_edit(self):
        self.ensure_one()
        return bool(
            self.env.su or self.owner_id == self.env.user
            or (self.visibility == "shared" and self.project_id._agile_role_for_user(self.env.user) == "manager")
        )

    # ---- validation and access --------------------------------------------------------

    @api.constrains("query", "project_id")
    def _check_query(self):
        for record in self:
            try:
                record._query_tool().compile(record.query or "")
            except QueryError as error:
                raise ValidationError(error.message) from None

    def _check_member(self, projects):
        if self.env.su:
            return
        for project in projects:
            if not project.agile_enabled or project._agile_role_for_user(self.env.user) == "none":
                raise AccessError(_("You must be a member of this Agile project to use its filters."))

    @api.model_create_multi
    def create(self, vals_list):
        projects = self.env["project.project"].browse([
            v.get("project_id") or self.env.context.get("default_project_id") for v in vals_list
        ]).exists()
        self._check_member(projects)
        for vals in vals_list:
            if not self.env.su:
                vals["owner_id"] = self.env.user.id
        return super().create(vals_list)

    def write(self, vals):
        if "project_id" in vals:
            raise ValidationError(_("A filter cannot be moved to another project."))
        own = {"my_digest", "my_send_empty"}
        if set(vals) - own and any(not r._can_edit() for r in self):
            raise AccessError(_("Only the owner or a project manager can change this filter."))
        if "owner_id" in vals and not self.env.su:
            raise AccessError(_("The owner of a filter cannot be changed. Save a copy instead."))
        return super().write(vals)

    def unlink(self):
        if any(not r._can_edit() for r in self):
            raise AccessError(_("Only the owner or a project manager can delete this filter."))
        return super().unlink()

    # ---- actions ------------------------------------------------------------------------

    def action_open_results(self):
        self.ensure_one()
        self.project_id._check_agile_backlog_access()
        action = self.project_id.action_open_agile_backlog()
        action["name"] = self.name
        action["domain"] = self._issue_domain()
        # The filter is the whole question: no "hide completed" default on top of it.
        action["context"] = {k: v for k, v in action["context"].items() if k != "search_default_agile_hide_completed"}
        return action

    def action_save_copy(self):
        self.ensure_one()
        copy = self.copy({"name": _("%s (copy)", self.name), "visibility": "private", "owner_id": self.env.user.id})
        return {
            "type": "ir.actions.act_window", "res_model": "agile.filter", "res_id": copy.id,
            "view_mode": "form", "views": [(False, "form")],
        }

    def action_export(self):
        self.ensure_one()
        return {"type": "ir.actions.act_url", "url": f"/agile/filter/{self.id}/export", "target": "self"}

    @api.model
    def action_open_for_project(self, project_id):
        project = self.env["project.project"].browse(project_id)
        project._check_agile_backlog_access()
        return {
            "type": "ir.actions.act_window", "name": _("Filters"), "res_model": "agile.filter",
            "view_mode": "list,form", "domain": [("project_id", "=", project.id)],
            "context": {"default_project_id": project.id},
        }

    # ---- the query bar (S-302): check, count and suggest in one call --------------------

    @api.model
    def agile_query_assist(self, project_id, text, cursor=None):
        project = self.env["project.project"].browse(project_id).exists()
        if not project:
            raise UserError(_("Open the filter from its project."))
        self._check_member(project)
        tool = AgileQuery(self.env, project)
        result = {"ok": False, "error": None, "words": "", "count": None, "rows": None,
                  "suggest": tool.suggest(text or "", cursor)}
        if not (text or "").strip():
            return result
        try:
            domain, words = tool.compile(text)
        except QueryError as error:
            result["error"] = {"message": error.message, "start": error.start, "end": error.end}
            return result
        result.update(
            ok=True, words=words, rows=tool.to_rows(text), basic_blockers=tool.basic_blockers(text),
            count=self.env["project.task"].search_count(
                [("project_id", "=", project.id), ("agile_issue", "=", True)] + domain),
        )
        return result

    @api.model
    def agile_query_options(self, project_id):
        project = self.env["project.project"].browse(project_id).exists()
        if not project:
            raise UserError(_("Open the filter from its project."))
        self._check_member(project)
        return AgileQuery(self.env, project).basic_options()

    # ---- export (S-303) ---------------------------------------------------------------------

    def _export_csv(self):
        """The results as CSV, read with the current user's own rights."""
        self.ensure_one()
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(EXPORT_HEAD)
        priority = dict(self.env["project.task"]._fields["priority"].selection)
        for task in self._issues():
            writer.writerow([_safe_cell(v) for v in (
                task.issue_key, task.name, task.agile_task_type_id.name, task.stage_id.name,
                ", ".join(task.user_ids.mapped("name")), task.sprint_id.name,
                priority.get(task.priority, ""), task.story_points if task.story_points_estimated else "",
                fields.Date.to_string(task.date_deadline.date()) if task.date_deadline else "",
            )])
        return out.getvalue()

    # ---- digest (S-303) -----------------------------------------------------------------------

    @api.model
    def _cron_send_digests(self):
        self.env["agile.filter.subscription"].sudo()._send_due()


class AgileFilterSubscription(models.Model):
    _name = "agile.filter.subscription"
    _description = "Agile Filter Email Subscription"

    filter_id = fields.Many2one("agile.filter", required=True, ondelete="cascade", index=True)
    user_id = fields.Many2one("res.users", required=True, ondelete="cascade", index=True)
    frequency = fields.Selection([("daily", "Every day"), ("weekly", "Every week")], required=True, default="daily")
    send_empty = fields.Boolean(string="Send even when empty")
    last_sent = fields.Datetime(readonly=True)

    _filter_user_unique = models.Constraint("unique (filter_id, user_id)", "You already get this filter by email.")

    def _is_due(self, now):
        self.ensure_one()
        if not self.last_sent:
            return True
        return now - self.last_sent >= timedelta(days=1 if self.frequency == "daily" else 7) - timedelta(hours=1)

    @api.model
    def _send_due(self):
        now = fields.Datetime.now()
        for subscription in self.search([]).filtered(lambda s: s._is_due(now)):
            try:
                with self.env.cr.savepoint():
                    subscription._send_digest()
            except Exception:  # one broken subscription must not stop the others
                _logger.exception("Agile filter digest %s failed", subscription.id)
            subscription.last_sent = now

    def _send_digest(self):
        """Mail the filter's issues to the subscriber, read with their own rights (at most 50)."""
        self.ensure_one()
        user = self.user_id
        digest = self.filter_id.with_user(user)
        if not user.active or user.share or not user.email:
            return False
        try:
            digest.check_access("read")
            digest.project_id._check_agile_backlog_access()
            issues = digest._issues(limit=DIGEST_LIMIT + 1)
        except (AccessError, UserError):
            return False  # the person lost access: send nothing
        if not issues and not self.send_empty:
            return False
        shown = issues[:DIGEST_LIMIT]
        rows = Markup("").join(
            Markup("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>") % (
                issue.issue_key or "", issue.name, issue.stage_id.name,
                ", ".join(issue.user_ids.mapped("name")))
            for issue in shown
        )
        total = len(issues) if len(issues) <= DIGEST_LIMIT else digest.match_count
        more = _("%(count)s more. Open the filter to see them all.", count=total - DIGEST_LIMIT) if total > DIGEST_LIMIT else ""
        base = self.env["ir.config_parameter"].sudo().get_str("web.base.url", "")
        link = f"{base}/odoo/agile.filter/{self.filter_id.id}"
        body = Markup(
            "<p>%(intro)s</p><table cellpadding='4'><tr><th>%(key)s</th><th>%(title)s</th><th>%(status)s</th>"
            "<th>%(assignee)s</th></tr>%(rows)s</table><p>%(more)s</p><p><a href='%(link)s'>%(open)s</a></p>"
        ) % {
            "intro": _("%(count)s issues match “%(name)s”.", count=len(shown) if len(issues) <= DIGEST_LIMIT else DIGEST_LIMIT,
                       name=self.filter_id.name),
            "key": _("Key"), "title": _("Title"), "status": _("Status"), "assignee": _("Assignee"),
            "rows": rows, "more": more, "link": quote(link, safe=":/"), "open": _("Open the filter"),
        }
        self.env["mail.mail"].sudo().create({
            "subject": _("%(project)s: %(name)s", project=self.filter_id.project_id.name, name=self.filter_id.name),
            "body_html": body,
            "email_to": user.email_formatted,
            "auto_delete": True,
        })
        return True


class ProjectTask(models.Model):
    _inherit = "project.task"

    agile_saved_filter_id = fields.Many2one(
        "agile.filter", string="Saved filter", compute="_compute_agile_saved_filter_id",
        search="_search_agile_saved_filter_id",
        help="Search only: finds the issues a saved filter finds, in the search box of the Backlog and Board.",
    )

    def _compute_agile_saved_filter_id(self):
        self.agile_saved_filter_id = False

    def _search_agile_saved_filter_id(self, operator, value):
        """A saved filter chosen in the search box: its query, read for the current user."""
        if operator in ("in", "=") and not isinstance(value, str):
            ids = [value] if isinstance(value, int) else list(value or [])
            ids = [i for i in ids if i]
            if not ids:
                return Domain.TRUE  # "no saved filter" is every issue
            filters = self.env["agile.filter"].search([("id", "in", ids)])  # record rules apply
        elif operator == "any":
            filters = self.env["agile.filter"].search(value)
        elif operator in ("ilike", "like", "=ilike") and isinstance(value, str):
            filters = self.env["agile.filter"].search([("name", "ilike", value)])
        else:
            return Domain.FALSE
        parts = []
        for saved in filters:
            try:
                parts.append(Domain.AND([saved._issue_domain()]))
            except UserError:
                continue  # a query that no longer reads finds nothing
        return Domain.OR(parts) if parts else Domain.FALSE


class ProjectProject(models.Model):
    _inherit = "project.project"

    def action_open_agile_filters(self):
        self.ensure_one()
        return self.env["agile.filter"].action_open_for_project(self.id)
