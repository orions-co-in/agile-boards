"""Move an issue to another project (S-1126): pick the project, map the statuses, confirm.

The issue gets a new key in the target project and keeps its old key as a redirect, so old links and the key
search still find it. Comments, history, links, attachments and worklogs stay with the issue.
"""
from odoo import Command, _, api, fields, models
from odoo.exceptions import AccessError, UserError

STEPS = [("target", "Project"), ("mapping", "Statuses"), ("confirm", "Confirm")]


class AgileIssueOldKey(models.Model):
    _name = "agile.issue.old.key"
    _description = "Agile Issue Former Key"
    _order = "id desc"

    task_id = fields.Many2one("project.task", required=True, index=True, ondelete="cascade", readonly=True)
    key = fields.Char(required=True, index=True, readonly=True)
    project_id = fields.Many2one("project.project", string="Former project", ondelete="set null", readonly=True)
    moved_on = fields.Datetime(default=fields.Datetime.now, readonly=True)

    _key_unique = models.Constraint("unique (key)", "A former key points to one issue.")

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise AccessError(_("Former keys are written by moving an issue."))
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError(_("Former keys cannot be changed."))

    def unlink(self):
        if not self.env.su and not self.env.context.get("module_uninstall"):
            raise AccessError(_("Former keys cannot be deleted."))
        return super().unlink()


class AgileMoveProjectLine(models.TransientModel):
    _name = "agile.move.project.line"
    _description = "Status mapping line for moving an issue"

    wizard_id = fields.Many2one("agile.move.project", required=True, ondelete="cascade")
    source_stage_id = fields.Many2one("project.task.type", string="Status in this project", readonly=True)
    target_stage_id = fields.Many2one(
        "project.task.type", string="Status in the new project",
        domain="[('project_ids', '=', parent.target_project_id), ('agile_status', '!=', False)]",
    )


class AgileMoveProject(models.TransientModel):
    _name = "agile.move.project"
    _description = "Move an Agile issue to another project"

    task_id = fields.Many2one("project.task", required=True, readonly=True, ondelete="cascade")
    source_project_id = fields.Many2one(related="task_id.project_id")
    target_project_id = fields.Many2one(
        "project.project", string="Move to", domain="[('agile_enabled', '=', True), ('id', '!=', source_project_id)]",
    )
    move_subtasks = fields.Boolean(string="Move sub-issues too", default=True)
    step = fields.Selection(STEPS, default="target", required=True)
    line_ids = fields.One2many("agile.move.project.line", "wizard_id", string="Statuses")
    blocker_text = fields.Text(compute="_compute_blockers")
    preview_text = fields.Text(compute="_compute_preview")
    subtask_count = fields.Integer(compute="_compute_subtask_count")

    @api.model
    def _agile_extra_blockers(self, task):
        """Hook: reasons agile_pro adds, such as a move waiting for approval."""
        return []

    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        task = self.env["project.task"].browse(self.env.context.get("default_task_id") or values.get("task_id"))
        if task:
            task._agile_check_can_move_project()
        return values

    # ---- what moves ---------------------------------------------------------------

    def _tasks(self):
        """The issue first, then its sub-issues at any depth when they move too."""
        self.ensure_one()
        tasks = self.task_id
        if self.move_subtasks:
            frontier = tasks
            while frontier:
                frontier = frontier.child_ids.filtered("agile_issue") - tasks
                tasks |= frontier
        return tasks

    @api.depends("task_id")
    def _compute_subtask_count(self):
        for wizard in self:
            wizard.subtask_count = len(wizard.task_id.child_ids.filtered("agile_issue"))

    def _blockers(self):
        """Plain sentences for everything that stops this move now."""
        self.ensure_one()
        task, target = self.task_id, self.target_project_id
        reasons = []
        if self.subtask_count and not self.move_subtasks:
            reasons.append(_("This issue has sub-issues. Move them with it, or move them first."))
        reasons += self._agile_extra_blockers(task)
        for issue in self._tasks():
            label = issue.issue_key or issue.name
            sprint = issue.sprint_id
            if sprint and sprint.state == "in_progress":
                reasons.append(_("%(key)s is in the active sprint %(sprint)s. Take it out of the sprint first.", key=label, sprint=sprint.name))
            elif sprint and sprint.state == "done":
                reasons.append(_("%(key)s is in the completed sprint %(sprint)s, and completed sprints keep their issues.", key=label, sprint=sprint.name))
            if target:
                issue_type = issue.agile_task_type_id
                if issue_type and issue_type.project_ids and target not in issue_type.project_ids:
                    reasons.append(_("%(key)s is a %(type)s, which %(project)s does not use.", key=label, type=issue_type.name, project=target.name))
                if issue.agile_restricted:
                    outside = (issue.agile_visible_user_ids | issue.user_ids) .filtered(lambda u: target._agile_role_for_user(u) == "none")
                    if outside:
                        reasons.append(_(
                            "%(key)s is restricted to people %(project)s does not include: %(names)s.",
                            key=label, project=target.name, names=", ".join(outside.mapped("name")),
                        ))
        return reasons

    @api.depends("task_id", "target_project_id", "move_subtasks")
    def _compute_blockers(self):
        for wizard in self:
            wizard.blocker_text = "\n".join(wizard._blockers()) if wizard.target_project_id else False

    def _stage_for(self, source_stage, target):
        """Same name first, else the target's main stage of the same category."""
        match = target.type_ids.filtered(lambda s: s.name.strip().lower() == source_stage.name.strip().lower() and s.agile_status)[:1]
        return match or self.env["project.task.type"]._agile_main_stage(target, source_stage.agile_status, include_archived=False)

    def _notes(self):
        """What is dropped or cleared by the move, in words."""
        self.ensure_one()
        target = self.target_project_id
        notes = []
        for issue in self._tasks():
            label = issue.issue_key or issue.name
            if issue.sprint_id:
                notes.append(_("%(key)s leaves its sprint %(sprint)s.", key=label, sprint=issue.sprint_id.name))
            if issue.version_id and not target.version_ids.filtered(lambda v: v.name == issue.version_id.name):
                notes.append(_("%(key)s loses its fix version %(version)s (no release with that name).", key=label, version=issue.version_id.name))
            if issue.agile_component_id and not target.agile_component_ids.filtered(lambda c: c.name == issue.agile_component_id.name):
                notes.append(_("%(key)s loses its component %(component)s.", key=label, component=issue.agile_component_id.name))
            gone = issue.user_ids.filtered(lambda u: target._agile_role_for_user(u) == "none")
            if gone:
                notes.append(_("%(key)s is no longer assigned to %(names)s (not on the new team).", key=label, names=", ".join(gone.mapped("name"))))
            if issue.parent_id and issue.parent_id not in self._tasks():
                notes.append(_("%(key)s is taken out from under its parent %(parent)s.", key=label, parent=issue.parent_id.issue_key or issue.parent_id.name))
            if issue.agile_affects_version_ids:
                notes.append(_("%(key)s keeps only the affected releases that exist in %(project)s.", key=label, project=target.name))
        return notes

    @api.depends("target_project_id", "move_subtasks", "line_ids.target_stage_id")
    def _compute_preview(self):
        for wizard in self:
            if not wizard.target_project_id:
                wizard.preview_text = False
                continue
            lines = [
                _("%(key)s gets a new key in %(project)s and keeps %(old)s as a redirect.",
                  key=wizard.task_id.issue_key or wizard.task_id.name, project=wizard.target_project_id.name,
                  old=wizard.task_id.issue_key or "its old key"),
            ] + wizard._notes()
            wizard.preview_text = "\n".join(lines)

    # ---- steps --------------------------------------------------------------------

    def _reopen(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": _("Move to another project"), "res_model": self._name,
            "res_id": self.id, "view_mode": "form", "target": "new",
        }

    def action_next(self):
        self.ensure_one()
        self.task_id._agile_check_can_move_project()
        if self.step == "target":
            if not self.target_project_id:
                raise UserError(_("Choose the project to move the issue to."))
            self._check_target()
            blockers = self._blockers()
            if blockers:
                raise UserError("\n".join(blockers))
            self.line_ids.unlink()
            stages = self._tasks().stage_id
            self.write({"line_ids": [
                Command.create({"source_stage_id": stage.id, "target_stage_id": self._stage_for(stage, self.target_project_id).id})
                for stage in stages
            ], "step": "mapping"})
        elif self.step == "mapping":
            if any(not line.target_stage_id for line in self.line_ids):
                raise UserError(_("Choose a status in %(project)s for every status shown.", project=self.target_project_id.name))
            self.step = "confirm"
        return self._reopen()

    def action_back(self):
        self.ensure_one()
        self.step = "mapping" if self.step == "confirm" else "target"
        return self._reopen()

    def _check_target(self):
        self.ensure_one()
        target = self.target_project_id
        if not target.agile_enabled or target == self.source_project_id:
            raise UserError(_("Choose another Agile project."))
        if not self.env.user.has_group("base.group_system") and target._agile_role_for_user(self.env.user) not in ("manager", "contributor"):
            raise AccessError(_("You need to be a manager or contributor of %(project)s to move an issue into it.", project=target.name))

    # ---- the move -----------------------------------------------------------------

    def action_move(self):
        self.ensure_one()
        self.task_id._agile_check_can_move_project()
        self._check_target()
        blockers = self._blockers()
        if blockers:
            raise UserError("\n".join(blockers))
        if any(not line.target_stage_id for line in self.line_ids):
            raise UserError(_("Choose a status in %(project)s for every status shown.", project=self.target_project_id.name))
        mapping = {line.source_stage_id.id: line.target_stage_id for line in self.line_ids}
        notes = self._notes()
        target, source = self.target_project_id, self.source_project_id
        moved = []
        tasks = self._tasks()
        # Odoo re-homes sub-tasks along with their parent, so read every issue's status and key first.
        plan = [(issue, issue.issue_key, source, mapping[issue.stage_id.id]) for issue in tasks]
        for issue, old_key, old_project, stage in plan:
            issue._agile_move_to_project(target, stage, tasks, old_key, old_project)
            moved.append((old_key,))
        main = self.task_id
        main.sudo().message_post(
            body=_("%(user)s moved this issue from %(source)s to %(target)s. Former key: %(old)s.", user=self.env.user.name, source=source.name, target=target.name, old=moved[0][0]),
            message_type="notification", subtype_xmlid="mail.mt_note",
        )
        for project in (source | target):
            project.sudo()._agile_audit("workflows", _("%(user)s moved %(old)s (now %(new)s) from %(source)s to %(target)s.", user=self.env.user.name, old=moved[0][0], new=main.issue_key, source=source.name, target=target.name))
        return {
            "type": "ir.actions.act_window", "res_model": "project.task", "res_id": main.id, "view_mode": "form",
            "views": [(False, "form")], "target": "current",
            "context": {"agile_move_notes": notes},
        }


class ProjectTask(models.Model):
    _inherit = "project.task"

    agile_old_key_ids = fields.One2many("agile.issue.old.key", "task_id", string="Former keys")
    agile_can_move_project = fields.Boolean(compute="_compute_agile_can_move_project")

    @api.depends_context("uid")
    @api.depends("project_id.agile_member_ids.role", "agile_issue")
    def _compute_agile_can_move_project(self):
        for task in self:
            task.agile_can_move_project = bool(
                task.id and task.agile_issue and (
                    self.env.user.has_group("base.group_system") or task.project_id._agile_role_for_user(self.env.user) == "manager"
                )
            )

    def _agile_check_can_move_project(self):
        self.ensure_one()
        if not self.agile_issue or not self.project_id.agile_enabled:
            raise UserError(_("Only Agile issues can be moved to another project."))
        if self.env.user.has_group("base.group_system"):
            return
        if self.project_id._agile_role_for_user(self.env.user) != "manager":
            raise AccessError(_("Only a manager of the project can move its issues to another project."))

    def _agile_move_to_project(self, target, target_stage, moving, old_key, source):
        """Re-home one issue. Runs with the system's rights after the wizard's checks."""
        self.ensure_one()
        task = self.sudo().with_context(agile_moving_project=True)
        if old_key:
            self.env["agile.issue.old.key"].sudo().create({"task_id": task.id, "key": old_key, "project_id": source.id})
        by_name = lambda records, name: records.filtered(lambda r: r.name == name)[:1]
        affected = [by_name(target.version_ids, v.name).id for v in task.agile_affects_version_ids if by_name(target.version_ids, v.name)]
        fix_version = by_name(target.version_ids, task.version_id.name).id
        component = by_name(target.agile_component_ids, task.agile_component_id.name).id
        # The first write re-homes the issue and clears what belongs to the old project; the checks of the
        # second write then run against the new project.
        values = {
            "project_id": target.id,
            "issue_key": task._allocate_key(target),
            "sprint_id": False,
            "agile_component_id": False,
            "version_id": False,
            "agile_affects_version_ids": [Command.clear()],
            "user_ids": [Command.set(task.user_ids.filtered(lambda u: target._agile_role_for_user(u) != "none").ids)],
        }
        if task.parent_id and task.parent_id not in moving:
            values["parent_id"] = False
        # Votes, links, documents, comments and worklogs follow the issue; project fields are re-pointed by name.
        task._agile_carry_custom_values(target)
        task.write(values)
        task.write({
            "stage_id": target_stage.id,
            "agile_component_id": component,
            "version_id": fix_version,
            "agile_affects_version_ids": [Command.set(affected)],
        })
        task._agile_ensure_custom_values()

    def _agile_carry_custom_values(self, target):
        """Hook: agile_pro re-points project field values to the target project's fields."""

    def _agile_ensure_custom_values(self):
        """Hook: agile_pro gives the issue an empty value for each project field."""

    def action_agile_move_project(self):
        self.ensure_one()
        self._agile_check_can_move_project()
        return {
            "type": "ir.actions.act_window", "name": _("Move to another project"), "res_model": "agile.move.project",
            "view_mode": "form", "target": "new", "context": {"default_task_id": self.id},
        }
