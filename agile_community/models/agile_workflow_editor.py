"""What the workflow editor needs on top of the data model (W-203)."""
from odoo import Command, _, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from markupsafe import Markup

NOTES_KEY = "agile_workflow_notes"
CONDITION_LABELS = {
    "require_no_open_subtasks": "all sub-issues done or canceled",
    "require_not_blocked": "the issue not blocked",
}
MAX_WORKFLOW_STATUSES = 12
ROLE_LABELS = {
    "allow_contributor": "Contributors",
    "allow_reviewer": "Reviewers",
    "allow_manager": "Managers",
}


class AgileWorkflowMixin(models.AbstractModel):
    _inherit = "agile.workflow.mixin"

    def _queue_workflow_note(self, workflow, line):
        """Collect change lines and post one history note per workflow when the transaction commits."""
        if self.env.context.get("agile_workflow_quiet"):
            return
        notes = self.env.cr.precommit.data.get(NOTES_KEY)
        if notes is None:
            notes = self.env.cr.precommit.data[NOTES_KEY] = {}
            env = self.env

            def post():
                for (workflow_id, project_id), lines in notes.items():
                    project = env["project.project"].browse(project_id).exists()
                    workflow = env["agile.workflow"].browse(workflow_id).exists()
                    if project and workflow and lines:
                        name = workflow.name or ""
                        body = Markup("<b>%s</b><br/>%s") % (name, Markup("<br/>").join(lines))
                        project._agile_post_audit_note(body, area="workflows")

            self.env.cr.precommit.add(post)
        notes.setdefault((workflow.id, workflow.project_id.id), []).append(line)


class AgileWorkflow(models.Model):
    _inherit = "agile.workflow"

    def _agile_custom_needs(self):
        """The project's own fields the canvas offers as further chips (agile_pro)."""
        return []

    diagram = fields.Json(compute="_compute_diagram", help="What the flow picture draws.")

    @api.depends_context("uid")
    @api.depends(
        "status_ids.stage_id", "status_ids.sequence", "status_ids.stage_id.active",
        "project_id.type_ids",
        "transition_ids.name", "transition_ids.from_status_id", "transition_ids.to_status_id",
        "transition_ids.allow_contributor", "transition_ids.allow_reviewer", "transition_ids.allow_manager",
    )
    def _compute_diagram(self):
        for workflow in self:
            counts = workflow._issue_counts()
            statuses = workflow.status_ids.sorted(lambda s: (s.sequence, s.id))
            workflow.diagram = {
                # The canvas edits the form's lists, so it needs the same right the lists need.
                "editable": bool(workflow._origin.id and workflow._origin.has_access("write")),
                "statuses": [
                    {
                        "stage_id": status.stage_id.id,
                        "name": status.stage_id.name,
                        "category": status.category,
                        "hidden": not status.stage_id.active,
                        "count": counts.get(status.stage_id.id, 0),
                    }
                    for status in statuses
                ],
                # Project statuses this workflow does not use yet (for "Use an existing status").
                "available": [
                    {"stage_id": stage.id, "name": stage.name, "category": stage.agile_status, "hidden": not stage.active}
                    for stage in workflow.project_id.with_context(active_test=False).type_ids.filtered("agile_status").sorted(
                        lambda s: (s.sequence, s.id))
                    if stage not in workflow.status_ids.stage_id
                ],
                "moves": [
                    {
                        "name": move.name or "",
                        "from": move.from_status_id.stage_id.id,
                        "to": move.to_status_id.stage_id.id,
                        "roles": [label for flag, label in ROLE_LABELS.items() if move[flag]],
                        "conditions": [label for flag, label in CONDITION_LABELS.items() if move[flag]]
                        + move._agile_extra_need_names(),
                    }
                    for move in workflow.transition_ids
                    if move.from_status_id and move.to_status_id
                ],
                # What a move can require, for the canvas panel's chips.
                "needs": [
                    {"id": field.id, "name": field.name}
                    for field in self.env["agile.workflow.field"].sudo().search([])
                ],
                # Who an action of a move may assign to.
                "people": [
                    {"id": user.id, "name": user.name}
                    for user in workflow.project_id.sudo().agile_member_ids.user_id.filtered(
                        lambda u: u.active and not u.share)
                ],
                # The project's own fields, offered as further chips (D-1021).
                "custom_needs": workflow._agile_custom_needs(),
            }

    def _issue_domain(self):
        """Issues this workflow governs: its own types, or for the default every type without one."""
        self.ensure_one()
        domain = [("project_id", "=", self.project_id.id), ("agile_issue", "=", True), ("active", "=", True)]
        if self.is_default:
            others = (self.project_id.agile_workflow_ids - self).task_type_ids
            if others:
                domain.append(("agile_task_type_id", "not in", others.ids))
        else:
            domain.append(("agile_task_type_id", "in", self.task_type_ids.ids))
        return domain

    def _issue_counts(self):
        """Issues per stage under this workflow."""
        self.ensure_one()
        if not self.id:
            return {}
        groups = self.env["project.task"].sudo()._read_group(self._issue_domain(), ["stage_id"], ["__count"])
        return {stage.id: count for stage, count in groups}

    @api.model_create_multi
    def create(self, vals_list):
        workflows = super().create(vals_list)
        for workflow in workflows.filtered(lambda w: not w.is_default and not w.status_ids):
            default = workflow.project_id.agile_workflow_ids.filtered("is_default")[:1]
            if default:
                workflow.with_context(agile_workflow_quiet=True)._copy_structure_from(default)
        for workflow in workflows:
            self._queue_workflow_note(workflow, _("Workflow created."))
        return workflows

    def _copy_structure_from(self, source):
        """Make this workflow's statuses and moves a copy of another workflow's."""
        self.ensure_one()
        self.sudo().transition_ids.unlink()
        self.sudo().status_ids.unlink()
        status_model = self.env["agile.workflow.status"].sudo()
        mapping = {}
        for status in source.status_ids.sorted(lambda s: (s.sequence, s.id)):
            mapping[status.id] = status_model.create({
                "workflow_id": self.id, "stage_id": status.stage_id.id, "sequence": status.sequence,
            })
        self.env["agile.workflow.transition"].sudo().create([
            {
                "name": move.name,
                "workflow_id": self.id,
                "from_status_id": mapping[move.from_status_id.id].id,
                "to_status_id": mapping[move.to_status_id.id].id,
                "allow_contributor": move.allow_contributor,
                "allow_reviewer": move.allow_reviewer,
                "allow_manager": move.allow_manager,
                "require_no_open_subtasks": move.require_no_open_subtasks,
                "require_not_blocked": move.require_not_blocked,
                "required_field_ids": [(6, 0, move.required_field_ids.ids)],
                **move._agile_copy_values(),
            }
            for move in source.transition_ids
        ])

    def agile_add_status(self, name, category):
        """Add a new status to the project (a stage) and to this workflow, after its category's last one."""
        self.ensure_one()
        self._check_workflow_managers(self.project_id)
        name = (name or "").strip()
        if not name:
            raise ValidationError(_("Give the status a name."))
        if category not in dict(self.env["project.task.type"]._fields["agile_status"].selection):
            raise ValidationError(_("Choose a category for the status."))
        if len(self.status_ids) >= MAX_WORKFLOW_STATUSES:
            raise ValidationError(
                _("A workflow can have %s statuses. Hide one first.", MAX_WORKFLOW_STATUSES)
            )
        stage = self.env["project.task.type"].with_context(active_test=False).create({
            "name": name,
            "agile_status": category,
            "fold": category == "canceled",
            "sequence": 1000,
            "project_ids": [Command.link(self.project_id.id)],
        })
        stage._agile_place_in_order(self.project_id)
        return self._agile_insert_status(stage)

    def _agile_status_line(self, stage_id):
        self.ensure_one()
        line = self.status_ids.filtered(lambda s: s.stage_id.id == stage_id)
        if not line:
            raise ValidationError(_("That status is not in this workflow."))
        return line

    def _agile_project_issues_in(self, stage):
        return self.env["project.task"].sudo().with_context(active_test=False).search([
            ("project_id", "=", self.project_id.id), ("stage_id", "=", stage.id), ("agile_issue", "=", True),
        ])

    def _agile_hand_over_main(self, stage):
        """When the main status of a category goes away, another one of that category becomes the main one."""
        if not stage.agile_is_main:
            return
        stage.sudo().agile_is_main = False
        successor = self.env["project.task.type"].search([
            ("project_ids", "=", self.project_id.id), ("agile_status", "=", stage.agile_status), ("id", "!=", stage.id),
        ], order="sequence, id", limit=1)
        if successor:
            successor.sudo().agile_is_main = True

    def agile_hide_status(self, stage_id, move_to_stage_id=None):
        """Archive a status for the whole project; issues in it move to another status first."""
        self.ensure_one()
        self._check_workflow_managers(self.project_id)
        stage = self._agile_status_line(stage_id).stage_id
        peers = self.env["project.task.type"].search([
            ("project_ids", "=", self.project_id.id), ("agile_status", "=", stage.agile_status), ("id", "!=", stage.id),
        ])
        if not peers:
            raise ValidationError(
                _("%(name)s is the only %(category)s status. Add another one before hiding it.",
                  name=stage.name, category=dict(stage._fields["agile_status"].selection)[stage.agile_status])
            )
        issues = self._agile_project_issues_in(stage)
        if issues:
            target = self.env["project.task.type"].browse(move_to_stage_id).exists() if move_to_stage_id else None
            if not target or target == stage or target.agile_status is False or target.active is False \
                    or self.project_id not in target.project_ids:
                raise ValidationError(
                    _("%(count)s issues are in %(name)s. Choose a status to move them to.", count=len(issues), name=stage.name)
                )
            issues.write({"stage_id": target.id})
        self._agile_hand_over_main(stage)
        stage.sudo().active = False
        self._queue_workflow_note(self, _("Hid status %(name)s.", name=stage.name))
        return True

    def agile_show_status(self, stage_id):
        self.ensure_one()
        self._check_workflow_managers(self.project_id)
        stage = self._agile_status_line(stage_id).stage_id.with_context(active_test=False)
        stage.sudo().active = True
        if not self.env["project.task.type"]._agile_main_stage(self.project_id, stage.agile_status, include_archived=False).agile_is_main:
            stage.sudo().agile_is_main = True
        self._queue_workflow_note(self, _("Showed status %(name)s again.", name=stage.name))
        return True

    def agile_remove_status(self, stage_id):
        """Take a status out of this workflow only; the project keeps it."""
        self.ensure_one()
        self._check_workflow_managers(self.project_id)
        line = self._agile_status_line(stage_id)
        name = line.stage_id.name
        line.unlink()  # refuses while issues of this workflow's types are in it
        self._queue_workflow_note(self, _("Removed status %(name)s from this workflow.", name=name))
        return True

    def agile_use_status(self, stage_id):
        """Add a status the project already has to this workflow."""
        self.ensure_one()
        self._check_workflow_managers(self.project_id)
        stage = self.env["project.task.type"].with_context(active_test=False).browse(stage_id).exists()
        if not stage or not stage.agile_status or self.project_id not in stage.project_ids:
            raise ValidationError(_("Choose a status of this project."))
        if self.status_ids.filtered(lambda s: s.stage_id == stage):
            raise ValidationError(_("%s is already in this workflow.", stage.name))
        if len(self.status_ids) >= MAX_WORKFLOW_STATUSES:
            raise ValidationError(_("A workflow can have %s statuses. Hide one first.", MAX_WORKFLOW_STATUSES))
        return self._agile_insert_status(stage)

    def agile_delete_status(self, stage_id):
        """Delete a status for good, only when no issue ever used it."""
        self.ensure_one()
        self._check_workflow_managers(self.project_id)
        stage = self._agile_status_line(stage_id).stage_id.with_context(active_test=False)
        if not self._agile_status_is_unused(stage):
            raise ValidationError(_("Issues have used %s. Hide it instead.", stage.name))
        peers = self.env["project.task.type"].search_count([
            ("project_ids", "=", self.project_id.id), ("agile_status", "=", stage.agile_status), ("id", "!=", stage.id),
        ])
        if not peers:
            raise ValidationError(_("%s is the only status of its category and cannot be deleted.", stage.name))
        name = stage.name
        self._agile_hand_over_main(stage)
        self.env["agile.workflow.status"].sudo().search([("stage_id", "=", stage.id)]).with_context(
            agile_workflow_quiet=True).unlink()
        stage.sudo().unlink()
        self._queue_workflow_note(self, _("Deleted status %(name)s.", name=name))
        return True

    def _agile_status_is_unused(self, stage):
        """True when no issue is in the status now and none ever moved through it."""
        if self.env["project.task"].sudo().with_context(active_test=False).search_count([("stage_id", "=", stage.id)]):
            return False
        field = self.env["ir.model.fields"]._get("project.task", "stage_id")
        return not self.env["mail.tracking.value"].sudo().search_count([
            ("field_id", "=", field.id), "|", ("old_value_integer", "=", stage.id), ("new_value_integer", "=", stage.id),
        ])

    def _agile_insert_status(self, stage):
        """Add a stage to this workflow after the last status of its category and renumber the lines."""
        lines = self.status_ids.sorted(lambda s: (s.sequence, s.id))
        last = max((i for i, line in enumerate(lines) if line.category == stage.agile_status), default=len(lines) - 1)
        status = self.env["agile.workflow.status"].create({
            "workflow_id": self.id, "stage_id": stage.id, "sequence": 1000,
        })
        ordered = list(lines[: last + 1]) + [status] + list(lines[last + 1:])
        for index, line in enumerate(ordered):
            if line.sequence != (index + 1) * 10:
                line.sequence = (index + 1) * 10
        return {"status_id": status.id, "stage_id": stage.id}

    def action_reset_to_default(self):
        self.ensure_one()
        self._check_workflow_managers(self.project_id)
        default = self.project_id.agile_workflow_ids.filtered("is_default")[:1]
        if self.is_default or not default:
            raise ValidationError(_("Only a workflow for issue types can be reset to the default."))
        self.with_context(agile_workflow_quiet=True)._copy_structure_from(default)
        self._queue_workflow_note(self, _("Statuses and moves were reset to the default workflow."))
        return True


class AgileWorkflowStatus(models.Model):
    _inherit = "agile.workflow.status"

    issue_count = fields.Integer(compute="_compute_issue_count")
    stage_active = fields.Boolean(related="stage_id.active", string="Shown")
    can_delete = fields.Boolean(compute="_compute_can_delete")

    @api.depends("workflow_id", "stage_id")
    def _compute_can_delete(self):
        for status in self:
            status.can_delete = bool(
                status.id and status.workflow_id._agile_status_is_unused(status.stage_id.with_context(active_test=False))
            )

    @api.depends("workflow_id", "stage_id")
    def _compute_issue_count(self):
        for status in self:
            status.issue_count = status.workflow_id._issue_counts().get(status.stage_id.id, 0) if status.workflow_id.id else 0

    @api.model_create_multi
    def create(self, vals_list):
        statuses = super().create(vals_list)
        for status in statuses:
            self._queue_workflow_note(status.workflow_id, _("Added status %(name)s.", name=status.stage_id.name))
        return statuses

    def unlink(self):
        for status in self:
            if status.issue_count and not self.env.context.get("agile_workflow_quiet"):
                raise ValidationError(
                    _(
                        "%(count)s issues of these types are in %(status)s. Move them first.",
                        count=status.issue_count, status=status.stage_id.name,
                    )
                )
        for status in self:
            self._queue_workflow_note(status.workflow_id, _("Removed status %(name)s.", name=status.stage_id.name))
        return super().unlink()


class AgileWorkflowTransition(models.Model):
    _inherit = "agile.workflow.transition"

    @api.model_create_multi
    def create(self, vals_list):
        moves = super().create(vals_list)
        for move in moves:
            self._queue_workflow_note(move.workflow_id, _(
                "Added move %(name)s: %(source)s to %(target)s.",
                name=move.name, source=move.from_status_id.stage_id.name, target=move.to_status_id.stage_id.name,
            ))
        return moves

    def write(self, vals):
        before = {
            move.id: (
                {flag: move[flag] for flag in ROLE_LABELS},
                (set(move.required_field_ids.ids), move._agile_extra_need_ids()),
                (move.name, move.from_status_id, move.to_status_id),
                {flag: move[flag] for flag in CONDITION_LABELS},
            )
            for move in self
        }
        result = super().write(vals)
        for move in self:
            roles, needs, shape, conditions = before[move.id]
            for flag, label in ROLE_LABELS.items():
                if move[flag] != roles[flag]:
                    self._queue_workflow_note(move.workflow_id, (
                        _("%(label)s can now take %(name)s.", label=_(label), name=move.name)
                        if move[flag] else
                        _("%(label)s can no longer take %(name)s.", label=_(label), name=move.name)
                    ))
            for flag, label in CONDITION_LABELS.items():
                if move[flag] != conditions[flag]:
                    self._queue_workflow_note(move.workflow_id, (
                        _("%(name)s now needs: %(label)s.", name=move.name, label=_(label))
                        if move[flag] else
                        _("%(name)s no longer needs: %(label)s.", name=move.name, label=_(label))
                    ))
            if (set(move.required_field_ids.ids), move._agile_extra_need_ids()) != needs:
                fields_text = ", ".join(
                    move.required_field_ids.mapped("name") + move._agile_extra_need_names()
                ) or _("nothing")
                self._queue_workflow_note(move.workflow_id, _(
                    "%(name)s now needs: %(fields)s.", name=move.name, fields=fields_text,
                ))
            if (move.name, move.from_status_id, move.to_status_id) != shape:
                self._queue_workflow_note(move.workflow_id, _(
                    "Move %(name)s is now %(source)s to %(target)s.",
                    name=move.name, source=move.from_status_id.stage_id.name, target=move.to_status_id.stage_id.name,
                ))
        return result

    def unlink(self):
        for move in self:
            self._queue_workflow_note(move.workflow_id, _(
                "Removed move %(name)s: %(source)s to %(target)s.",
                name=move.name, source=move.from_status_id.stage_id.name, target=move.to_status_id.stage_id.name,
            ))
        return super().unlink()


class ProjectProject(models.Model):
    _inherit = "project.project"

    def action_open_agile_workflows(self):
        self.ensure_one()
        if not self.agile_enabled or self._agile_role_for_user(self.env.user) != "manager":
            raise AccessError(_("Only this project's Agile Manager can open its workflows."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Workflows"),
            "res_model": "agile.workflow",
            "view_mode": "list,form",
            "domain": [("project_id", "=", self.id)],
            "context": {"default_project_id": self.id},
        }
