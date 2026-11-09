from odoo import Command, _, api, fields, models
from odoo.exceptions import AccessError, UserError


class AgileBulkUpdateWizard(models.TransientModel):
    _name = "agile_community.bulk_update_wizard"
    _description = "Bulk update Agile issues"

    task_ids = fields.Many2many("project.task", string="Selected issues", readonly=True)
    task_count = fields.Integer(compute="_compute_task_count")
    preview_result = fields.Text(string="Impact preview", compute="_compute_preview_result")
    sprint_membership_snapshot = fields.Json(readonly=True, copy=False)
    project_ids = fields.Many2many(
        "project.project", compute="_compute_project_ids"
    )
    update_assignees = fields.Boolean(string="Change assignees")
    assignee_operation = fields.Selection(
        [("replace", "Set assignees to"), ("add", "Add assignees"), ("remove", "Remove assignees")],
        default="replace",
    )
    assignee_ids = fields.Many2many(
        "res.users",
        "agile_bulk_update_user_rel",
        "wizard_id",
        "user_id",
        string="Assignees",
        domain=[("share", "=", False), ("active", "=", True)],
    )
    update_tags = fields.Boolean(string="Change labels")
    tag_operation = fields.Selection(
        [("replace", "Set labels to"), ("add", "Add labels"), ("remove", "Remove labels")],
        default="add",
    )
    tag_ids = fields.Many2many(
        "project.tags",
        "agile_bulk_update_tag_rel",
        "wizard_id",
        "tag_id",
        string="Labels",
    )
    update_sprint = fields.Boolean(string="Change sprint")
    sprint_operation = fields.Selection(
        [("move", "Move to sprint"), ("backlog", "Return to backlog")],
        default="move",
    )
    sprint_id = fields.Many2one(
        "project.sprint",
        string="Destination sprint",
        domain="[('project_id', 'in', project_ids), ('state', '!=', 'done')]",
    )

    # The everyday fields Jira's bulk edit offers (NU-13).
    update_status = fields.Boolean(string="Change status")
    stage_id = fields.Many2one(
        "project.task.type", string="Move to status",
        domain="[('project_ids', 'in', project_ids), ('agile_status', '!=', False)]",
    )
    update_priority = fields.Boolean(string="Change priority")
    priority = fields.Selection(lambda self: self.env["project.task"]._fields["priority"].selection, default="0")
    update_points = fields.Boolean(string="Change points")
    story_points = fields.Float(string="Points", digits=(16, 2))
    update_version = fields.Boolean(string="Change fix version")
    version_id = fields.Many2one(
        "project.version", string="Fix version",
        domain="[('project_id', 'in', project_ids), ('state', '=', 'planned')]",
    )
    update_epic = fields.Boolean(string="Change epic")
    epic_id = fields.Many2one(
        "project.task", string="Epic",
        domain="[('project_id', 'in', project_ids), ('agile_is_epic', '=', True)]",
    )

    @api.model_create_multi
    def create(self, vals_list):
        wizards = super().create(vals_list)
        for wizard in wizards:
            snapshot = {
                str(task.id): task.sprint_id.id or False
                for task in wizard.task_ids
            }
            super(AgileBulkUpdateWizard, wizard).write(
                {"sprint_membership_snapshot": snapshot}
            )
        return wizards

    def write(self, vals):
        if {"sprint_membership_snapshot", "task_ids"} & vals.keys():
            raise AccessError(
                _("The selected issue set is locked and sprint membership snapshots are system managed.")
            )
        return super().write(vals)

    def _compute_task_count(self):
        for wizard in self:
            wizard.task_count = len(wizard.task_ids)

    @api.depends("task_ids.project_id")
    def _compute_project_ids(self):
        for wizard in self:
            wizard.project_ids = wizard.task_ids.mapped("project_id")

    def _any_update(self):
        self.ensure_one()
        return any((
            self.update_assignees, self.update_tags, self.update_sprint, self.update_status,
            self.update_priority, self.update_points, self.update_version, self.update_epic,
        ))

    def _get_preview_validation(self):
        self.ensure_one()
        global_errors = []
        errors_by_task = {}
        if not self.task_ids:
            global_errors.append(_("No issues were selected."))
        if not self._any_update():
            global_errors.append(
                _("Choose whether to change assignees, labels, sprint, status, priority, points, fix version or epic.")
            )
        if self.update_status and not self.stage_id:
            global_errors.append(_("Select the status the issues move to."))
        if self.update_version and not self.version_id:
            global_errors.append(_("Select the fix version."))
        if self.update_assignees and self.assignee_operation != "replace" and not self.assignee_ids:
            global_errors.append(_("Select at least one assignee to add or remove."))
        if self.update_tags and self.tag_operation != "replace" and not self.tag_ids:
            global_errors.append(_("Select at least one label to add or remove."))
        if self.update_sprint and self.sprint_operation == "move" and not self.sprint_id:
            global_errors.append(_("Select a destination sprint."))

        for task in self.task_ids:
            messages = errors_by_task.setdefault(task.id, [])
            if not task.agile_issue:
                messages.append(_("this is not an Agile issue."))
                continue
            if task._agile_role() not in ("manager", "contributor"):
                messages.append(_("only Agile team members can bulk edit issues."))
                continue
            try:
                task.check_access("write")
            except AccessError as error:
                messages.append(_("you cannot edit this issue (%s)") % error)
                continue
            if self.update_tags:
                invalid_tags = self.tag_ids.filtered(
                    lambda tag: tag.project_ids and task.project_id not in tag.project_ids
                )
                if invalid_tags:
                    messages.append(
                        _("label(s) %(labels)s are not available in project %(project)s.",
                          labels=", ".join(invalid_tags.mapped("display_name")),
                          project=task.project_id.display_name)
                    )
            if self.update_status and self.stage_id:
                if self.stage_id not in task.project_id.type_ids:
                    messages.append(_("the status %(stage)s does not exist in this project.", stage=self.stage_id.name))
                else:
                    try:
                        task._check_agile_transition(self.stage_id.agile_status, self.stage_id)
                    except UserError as error:
                        messages.append(str(error))
            if self.update_version and self.version_id and self.version_id.project_id != task.project_id:
                messages.append(_("the fix version belongs to another project."))
            if self.update_epic and self.epic_id and self.epic_id.project_id != task.project_id:
                messages.append(_("the epic belongs to another project."))
            if self.update_sprint:
                if not task.project_id.use_scrum:
                    messages.append(_("sprint changes require a Scrum-enabled project."))
                elif self.sprint_operation == "move" and self.sprint_id:
                    if self.sprint_id.state == "done":
                        messages.append(_("a completed sprint cannot receive issues."))
                    elif self.sprint_id.project_id != task.project_id:
                        messages.append(_("the destination sprint belongs to another project."))

        if self.update_assignees:
            invalid_users = self.assignee_ids.filtered(lambda user: user.share or not user.active)
            if invalid_users:
                global_errors.append(
                    _("These assignees must be active internal users: %s.")
                    % ", ".join(invalid_users.mapped("display_name"))
                )
        return global_errors, errors_by_task

    def _describe_requested_changes(self):
        self.ensure_one()
        changes = []
        if self.update_assignees:
            names = ", ".join(self.assignee_ids.mapped("display_name")) or _("no assignees")
            if self.assignee_operation == "replace":
                changes.append(_("Set assignees to %(names)s", names=names))
            else:
                changes.append(_("%(operation)s assignees: %(names)s", operation=self.assignee_operation.title(), names=names))
        if self.update_tags:
            names = ", ".join(self.tag_ids.mapped("display_name")) or _("no labels")
            if self.tag_operation == "replace":
                changes.append(_("Set labels to %(names)s", names=names))
            else:
                changes.append(_("%(operation)s labels: %(names)s", operation=self.tag_operation.title(), names=names))
        if self.update_status:
            changes.append(_("Move issues to status %(stage)s", stage=self.stage_id.name or _("not selected")))
        if self.update_priority:
            labels = dict(self.env["project.task"]._fields["priority"].selection)
            changes.append(_("Set priority to %(priority)s", priority=labels.get(self.priority, self.priority)))
        if self.update_points:
            changes.append(_("Set points to %(points)s", points=self.story_points))
        if self.update_version:
            changes.append(_("Set fix version to %(version)s", version=self.version_id.display_name or _("not selected")))
        if self.update_epic:
            changes.append(_("Set epic to %(epic)s", epic=self.epic_id.display_name or _("no epic")))
        if self.update_sprint:
            changes.append(
                _("Return issues to the backlog")
                if self.sprint_operation == "backlog"
                else _("Move issues to sprint %(sprint)s", sprint=self.sprint_id.display_name or _("not selected"))
            )
        return "; ".join(changes) or _("No updates selected")

    @api.depends(
        "task_ids", "update_assignees", "assignee_operation", "assignee_ids",
        "update_tags", "tag_operation", "tag_ids", "update_sprint",
        "sprint_operation", "sprint_id", "update_status", "stage_id", "update_priority", "priority",
        "update_points", "story_points", "update_version", "version_id", "update_epic", "epic_id",
    )
    def _compute_preview_result(self):
        for wizard in self:
            if not wizard._any_update():
                wizard.preview_result = _("Select changes to preview their impact.")
                continue
            global_errors, errors_by_task = wizard._get_preview_validation()
            lines = [
                _("Requested changes: %(changes)s", changes=wizard._describe_requested_changes()),
                _("Affected issues (%(count)s):", count=len(wizard.task_ids)),
            ]
            for task in wizard.task_ids:
                label = task.issue_key or task.display_name
                messages = errors_by_task.get(task.id) or []
                lines.append(
                    _("%(issue)s — %(result)s", issue=label, result="; ".join(messages) or _("Can be updated"))
                )
            if global_errors:
                lines.append(_("Request validation: %(errors)s", errors="; ".join(global_errors)))
            lines.append(_("Nothing changes until Apply; eligibility is checked again when submitted."))
            wizard.preview_result = "\n".join(lines)

    def action_apply(self):
        self.ensure_one()
        global_errors, errors_by_task = self._get_preview_validation()
        errors = list(global_errors)
        for task in self.task_ids:
            label = task.issue_key or task.display_name
            errors.extend(
                _("%(issue)s: %(error)s", issue=label, error=message)
                for message in errors_by_task.get(task.id, [])
            )
        if errors:
            raise UserError(_("Nothing was changed. Fix these issues and try again:\n%s") % "\n".join(errors))

        if self.update_sprint:
            task_ids = sorted(self.task_ids.ids)
            self.env.cr.execute(
                "SELECT id FROM project_task WHERE id = ANY(%s) ORDER BY id FOR UPDATE",
                (task_ids,),
            )
            self.task_ids.invalidate_recordset(["sprint_id", "project_id", "state"])
            if self.sprint_operation == "move" and self.sprint_id:
                self.env.cr.execute(
                    "SELECT id FROM project_sprint WHERE id = %s FOR UPDATE",
                    (self.sprint_id.id,),
                )
                self.sprint_id.invalidate_recordset(["state", "project_id"])
            snapshot = self.sprint_membership_snapshot or {}
            stale_tasks = [
                task
                for task in self.task_ids
                if snapshot.get(str(task.id), False) != (task.sprint_id.id or False)
            ]
            if stale_tasks:
                raise UserError(
                    _(
                        "Nothing was changed. Sprint membership changed after this editor opened:\n%s"
                    )
                    % "\n".join(
                        task.issue_key or task.display_name for task in stale_tasks
                    )
                )

        # Each write has a savepoint so validation can report all failing issues.
        # Raising afterward rolls successful writes back too: bulk edits are atomic.
        write_errors = []
        for task in self.task_ids:
            values = {}
            if self.update_assignees:
                current = set(task.user_ids.ids)
                selected = set(self.assignee_ids.ids)
                if self.assignee_operation == "replace":
                    updated = selected
                elif self.assignee_operation == "add":
                    updated = current | selected
                else:
                    updated = current - selected
                if updated != current:
                    values["user_ids"] = [Command.set(sorted(updated))]
            if self.update_tags:
                current = set(task.tag_ids.ids)
                selected = set(self.tag_ids.ids)
                if self.tag_operation == "replace":
                    updated = selected
                elif self.tag_operation == "add":
                    updated = current | selected
                else:
                    updated = current - selected
                if updated != current:
                    values["tag_ids"] = [Command.set(sorted(updated))]
            if self.update_status and self.stage_id and task.stage_id != self.stage_id:
                values["stage_id"] = self.stage_id.id
            if self.update_priority and task.priority != self.priority:
                values["priority"] = self.priority
            if self.update_points and task.story_points != self.story_points:
                values["story_points"] = self.story_points
            if self.update_version and task.version_id != self.version_id:
                values["version_id"] = self.version_id.id
            if self.update_epic and task.parent_id != self.epic_id:
                values["parent_id"] = self.epic_id.id or False
            if self.update_sprint:
                target_sprint_id = (
                    self.sprint_id.id if self.sprint_operation == "move" else False
                )
                if task.sprint_id.id != target_sprint_id:
                    values["sprint_id"] = target_sprint_id
            if values:
                try:
                    with self.env.cr.savepoint():
                        task.write(values)
                except (AccessError, UserError, ValueError) as error:
                    write_errors.append(_("%s: %s") % (task.issue_key or task.display_name, error))

        if write_errors:
            raise UserError(_("Nothing was changed. These issues could not be updated:\n%s") % "\n".join(write_errors))
        return {"type": "ir.actions.act_window_close", "infos": {"success": True}}
