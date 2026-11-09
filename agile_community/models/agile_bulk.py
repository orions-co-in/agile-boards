"""Bulk edit of issues from the Backlog and the Board (S-931)."""
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

BULK_LIMIT = 100
BULK_CHANGES = (
    "assignee", "sprint", "status", "label_add", "label_remove", "type", "priority", "due", "watch", "unwatch",
)
# What an Undo may write back; every write still goes through the ordinary permission checks.
RESTORE_FIELDS = ("user_ids", "sprint_id", "tag_ids", "agile_task_type_id", "priority", "date_deadline")


class ProjectTask(models.Model):
    _inherit = "project.task"

    @api.model
    def agile_bulk_update(self, ids, change, value=None, confirmed=False):
        """Apply one change to several issues, each on its own so one refusal never blocks the rest.

        Returns what changed, what was refused and why, and what an Undo needs. A sprint change that
        takes issues out of a running sprint first answers {"needs_confirm": ...} unless confirmed.
        """
        if change not in BULK_CHANGES:
            raise UserError(_("That change is not available for several issues."))
        ids = list(dict.fromkeys(ids or []))
        if not ids:
            raise UserError(_("Select at least one issue."))
        if len(ids) > BULK_LIMIT:
            raise UserError(_("Select up to %s issues.", BULK_LIMIT))
        tasks = self.browse(ids).exists()
        tasks.check_access("read")
        projects = tasks.project_id
        if len(projects) != 1 or not projects.agile_enabled:
            raise UserError(_("Select issues of one Agile project."))
        target = self._agile_bulk_target(projects, change, value)
        if change == "sprint" and not confirmed:
            leaving = tasks.filtered(
                lambda t: t.sprint_id.state == "in_progress" and t.sprint_id.id != (value or False)
            )
            if leaving:
                return {
                    "needs_confirm": len(leaving),
                    "sprint": leaving[0].sprint_id.name,
                    "changed": [], "refused": [], "restore": [],
                }
        changed, refused, restore = [], [], []
        # An id that names no issue is reported, not silently dropped (E2E-015).
        for missing in [i for i in ids if i not in tasks.ids]:
            refused.append({"id": missing, "key": "", "name": "", "reason": _("There is no issue with this id.")})
        for task in tasks:
            before = {}
            try:
                with self.env.cr.savepoint():
                    before = task._agile_bulk_apply(change, value, target)
            except (UserError, AccessError, ValidationError) as error:
                refused.append({
                    "id": task.id, "key": task.issue_key or "", "name": task.name,
                    "reason": error.args[0] if error.args else str(error),
                })
                continue
            changed.append(task.id)
            if before:
                restore.append({"id": task.id, "vals": before})
        return {"changed": changed, "refused": refused, "restore": restore, "needs_confirm": 0}

    @api.model
    def _agile_bulk_target(self, project, change, value):
        """The record a change points at, checked once for the whole batch."""
        if change == "assignee" and value:
            user = self.env["res.users"].browse(value).exists()
            if not user or project._agile_role_for_user(user) not in ("manager", "contributor"):
                raise UserError(_("Choose someone who can work on this project."))
            return user
        if change == "sprint" and value:
            sprint = self.env["project.sprint"].browse(value).exists()
            if not sprint or sprint.project_id != project:
                raise UserError(_("Choose a sprint of this project."))
            return sprint
        if change == "status":
            stage = self.env["project.task.type"].browse(value).exists() if value else None
            if not stage or project not in stage.project_ids or not stage.agile_status or not stage.active:
                raise UserError(_("Choose a status of this project."))
            return stage
        if change == "type":
            issue_type = self.env["agile_community.task_type"].browse(value).exists() if value else None
            if not issue_type or not issue_type.active or (
                issue_type.project_ids and project not in issue_type.project_ids
            ):
                raise UserError(_("Choose an issue type of this project."))
            return issue_type
        if change == "priority":
            if value not in dict(self._fields["priority"].selection):
                raise UserError(_("Choose a priority."))
            return value
        if change == "due":
            if not value:
                return False  # clears the due date
            try:
                return fields.Date.to_date(value)
            except (ValueError, TypeError):
                raise UserError(_("Choose a valid due date.")) from None
        if change in ("label_add", "label_remove"):
            tag = self.env["project.tags"].browse(value).exists() if value else None
            if not tag:
                raise UserError(_("Choose a label."))
            return tag
        return None

    def _agile_bulk_apply(self, change, value, target):
        """Change one issue; return what an Undo must write back (empty when it cannot be undone)."""
        self.ensure_one()
        if change == "assignee":
            before = {"user_ids": [(6, 0, self.user_ids.ids)]}
            self.write({"user_ids": [(6, 0, [target.id] if target else [])]})
            return before
        if change == "sprint":
            before = {"sprint_id": self.sprint_id.id or False}
            self.write({"sprint_id": target.id if target else False})
            return before
        if change == "type":
            before = {"agile_task_type_id": self.agile_task_type_id.id or False}
            self.write({"agile_task_type_id": target.id})
            return before
        if change == "priority":
            before = {"priority": self.priority}
            self.write({"priority": target})
            return before
        if change == "due":
            before = {"date_deadline": fields.Datetime.to_string(self.date_deadline) if self.date_deadline else False}
            self.write({"date_deadline": target or False})
            return before
        if change in ("watch", "unwatch"):
            partner = self.env.user.partner_id
            watching = partner in self.message_partner_ids
            if change == "watch" and not watching:
                self.message_subscribe(partner_ids=partner.ids)
            elif change == "unwatch" and watching:
                self.message_unsubscribe(partner_ids=partner.ids)
            else:
                raise UserError(_("You already watch it.") if change == "watch" else _("You are not watching it."))
            return {"_watching": watching}
        if change == "label_add":
            before = {"tag_ids": [(6, 0, self.tag_ids.ids)]}
            self.write({"tag_ids": [(4, target.id)]})
            return before
        if change == "label_remove":
            before = {"tag_ids": [(6, 0, self.tag_ids.ids)]}
            self.write({"tag_ids": [(3, target.id)]})
            return before
        # status: the issue's own workflow must have a move from where it is to the chosen status.
        if self.stage_id == target:
            raise UserError(_("It is already in %s.", target.name))
        if self._agile_workflow() and not self._agile_workflow_transition(target):
            raise UserError(_("No move from %(source)s to %(target)s.", source=self.stage_id.name, target=target.name))
        self.write({"stage_id": target.id})
        return {}

    @api.model
    def agile_bulk_restore(self, items):
        """Undo a bulk change: write the earlier values back, issue by issue."""
        undone, refused = [], []
        for item in items or []:
            task = self.browse(item.get("id")).exists()
            raw = item.get("vals") or {}
            vals = {key: value for key, value in raw.items() if key in RESTORE_FIELDS}
            if not task or not (vals or "_watching" in raw):
                continue
            try:
                with self.env.cr.savepoint():
                    if vals:
                        task.write(vals)
                    if "_watching" in raw:
                        partner = self.env.user.partner_id
                        if raw["_watching"]:
                            task.message_subscribe(partner_ids=partner.ids)
                        else:
                            task.message_unsubscribe(partner_ids=partner.ids)
                undone.append(task.id)
            except (UserError, AccessError, ValidationError) as error:
                refused.append({
                    "id": task.id, "key": task.issue_key or "", "name": task.name,
                    "reason": error.args[0] if error.args else str(error),
                })
        return {"undone": undone, "refused": refused}


class ProjectProject(models.Model):
    _inherit = "project.project"

    def agile_bulk_options(self):
        """The choices the bulk bar offers: people, open sprints, statuses and labels."""
        self.ensure_one()
        self._check_agile_backlog_access()
        members = self.agile_member_ids.filtered(
            lambda m: m.user_id.active and m.role in ("manager", "contributor")
        )
        stages = self.env["project.task.type"].search([
            ("project_ids", "=", self.id), ("agile_status", "!=", False), ("agile_status", "!=", "canceled"),
        ], order="sequence, id")
        return {
            "members": [{"id": m.user_id.id, "name": m.user_id.name} for m in members],
            "sprints": [
                {"id": s.id, "name": s.name, "state": s.state}
                for s in self.sprint_ids.filtered(lambda s: s.state != "done").sorted(lambda s: (s.date_start, s.id))
            ],
            "statuses": [{"id": s.id, "name": s.name, "category": s.agile_status} for s in stages],
            "tags": [
                {"id": t.id, "name": t.name}
                for t in self.env["project.tags"].search([], order="name", limit=60)
            ],
            "types": [
                {"id": t.id, "name": t.name}
                for t in self.env["agile_community.task_type"].search(
                    [("active", "=", True), "|", ("project_ids", "=", False), ("project_ids", "=", self.id)]
                )
            ],
            "priorities": [
                {"id": code, "name": name} for code, name in self.env["project.task"]._fields["priority"].selection
            ],
        }
