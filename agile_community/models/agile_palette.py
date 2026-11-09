import re

from odoo import api, fields, models
from odoo.exceptions import AccessError

RECENT_LIMIT = 10
SEARCH_LIMIT = 8
MIN_CROSS_PROJECT = 2  # characters needed before other projects are searched by words
KEY_LIKE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*-\d+$")


class AgileRecentIssue(models.Model):
    """The issues a person opened last, for the command palette (K-1032). Written only by the server."""

    _name = "agile.recent.issue"
    _description = "Agile Recently Viewed Issue"
    _order = "visited_at desc, id desc"

    user_id = fields.Many2one("res.users", required=True, ondelete="cascade", index=True)
    task_id = fields.Many2one("project.task", required=True, ondelete="cascade", index=True)
    project_id = fields.Many2one("project.project", required=True, ondelete="cascade", index=True)
    visited_at = fields.Datetime(required=True, default=fields.Datetime.now)

    _user_task_unique = models.Constraint("unique (user_id, task_id)", "An issue is listed once per person.")


class ProjectTask(models.Model):
    _inherit = "project.task"

    @api.model
    def _agile_palette_row(self, task):
        return {
            "id": task.id,
            "key": task.issue_key or "",
            "name": task.name,
            "project": task.project_id.name,
            "project_id": task.project_id.id,
            "status": task.stage_id.name or "",
        }

    def agile_palette_visit(self):
        """Remember that the current person opened this issue. Silent for an issue they cannot read."""
        self.ensure_one()
        if not self.agile_issue:
            return False
        try:
            self.check_access("read")
        except AccessError:
            return False
        recent = self.env["agile.recent.issue"].sudo()
        user, task = self.env.user, self.sudo()
        found = recent.search([("user_id", "=", user.id), ("task_id", "=", task.id)])
        if found:
            found.visited_at = fields.Datetime.now()
        else:
            recent.create({"user_id": user.id, "task_id": task.id, "project_id": task.project_id.id})
        # Keep the newest RECENT_LIMIT per person and project.
        rows = recent.search([("user_id", "=", user.id), ("project_id", "=", task.project_id.id)])
        rows[RECENT_LIMIT:].unlink()
        return True

    @api.model
    def agile_palette_recent(self, project_id):
        """The issues this person opened last in a project, newest first; unreadable ones are left out."""
        rows = self.env["agile.recent.issue"].sudo().search([
            ("user_id", "=", self.env.user.id), ("project_id", "=", project_id)], limit=RECENT_LIMIT)
        readable = self.search([("id", "in", rows.task_id.ids), ("agile_issue", "=", True)])
        return [self._agile_palette_row(task) for task in rows.task_id if task in readable]

    @api.model
    def agile_palette_search(self, term, project_id=False):
        """Issues for a typed key or words of a title: this project first, then every other project the person can read.

        Everything goes through the person's own access rules, so a restricted issue gives the same empty
        answer as a key that does not exist.
        """
        term = (term or "").strip()
        if not term:
            return []
        found = self.browse()
        base = [("agile_issue", "=", True)]
        if KEY_LIKE.match(term):
            # Keys are zero padded (QA-0003), so QA-3 is accepted as well.
            prefix, number = term.rsplit("-", 1)
            padded = f"{prefix}-{int(number):04d}"
            found = self.search(
                base + ["|", "|", ("issue_key", "=ilike", term), ("issue_key", "=ilike", padded),
                        ("agile_old_key_ids.key", "=ilike", term)], limit=SEARCH_LIMIT)
        words = ["|", ("name", "ilike", term), ("issue_key", "ilike", term)]
        if project_id and len(found) < SEARCH_LIMIT:
            found |= self.search(
                base + [("project_id", "=", project_id)] + words,
                limit=SEARCH_LIMIT - len(found), order="write_date desc, id desc")
        if len(term) >= MIN_CROSS_PROJECT and len(found) < SEARCH_LIMIT:
            found |= self.search(
                base + [("project_id", "!=", project_id or 0), ("id", "not in", found.ids)] + words,
                limit=SEARCH_LIMIT - len(found), order="write_date desc, id desc")
        return [self._agile_palette_row(task) for task in found]
