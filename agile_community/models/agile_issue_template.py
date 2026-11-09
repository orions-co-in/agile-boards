from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


class AgileIssueChecklistItem(models.Model):
    _name = "agile.issue.checklist.item"
    _description = "Agile Issue Checklist Item"
    _order = "sequence, id"

    task_id = fields.Many2one(
        "project.task", required=True, index=True, ondelete="cascade"
    )
    sequence = fields.Integer(default=10)
    name = fields.Char(string="Checklist item", required=True)
    is_done = fields.Boolean(string="Done", copy=False, default=False)

    def _check_task_editable(self, task):
        if not (task.agile_issue or task.is_template) or not task.project_id.agile_enabled:
            raise ValidationError(
                _("Checklist items can only be added to Agile issues or templates.")
            )
        if self.env.su and task.recurrence_id:
            return
        if not task.project_id.with_user(self.env.user).has_access("read"):
            raise AccessError(
                _("You must retain native Odoo Project access to edit this checklist.")
            )
        role = task.project_id._agile_role_for_user(self.env.user)
        if role not in ("manager", "contributor") or (
            task.is_template and role != "manager"
        ):
            raise AccessError(
                _("Only Agile managers and contributors can edit issue checklists; templates are manager-only.")
            )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            task = self.env["project.task"].browse(vals.get("task_id")).exists()
            self._check_task_editable(task)
        return super().create(vals_list)

    def write(self, vals):
        tasks = self.mapped("task_id")
        if vals.get("task_id"):
            tasks |= self.env["project.task"].browse(vals["task_id"])
        for task in tasks:
            self._check_task_editable(task)
        return super().write(vals)

    def unlink(self):
        for task in self.mapped("task_id"):
            self._check_task_editable(task)
        return super().unlink()

    @api.constrains("task_id")
    def _check_project_scope(self):
        for item in self:
            if not item.task_id.project_id.agile_enabled:
                raise ValidationError(
                    _("Checklist items must belong to an Agile project.")
                )


class AgileIssueTemplateMixin(models.Model):
    _inherit = "project.task"

    agile_acceptance_criteria = fields.Html(
        string="Acceptance Criteria", sanitize=True, copy=True
    )
    agile_checklist_item_ids = fields.One2many(
        "agile.issue.checklist.item",
        "task_id",
        string="Acceptance Checklist",
        copy=True,
    )

    @api.model
    def _get_template_field_blacklist(self):
        return list(set(super()._get_template_field_blacklist()) | {
            "agile_blocked",
            "agile_block_reason",
            "agile_planned_start",
            "agile_planned_end",
            "recurrence_id",
            "recurring_task",
            "sprint_id",
            "version_id",
        })

    def create(self, vals_list):
        for vals in vals_list:
            project = self.env["project.project"].browse(
                vals.get("project_id") or self.env.context.get("default_project_id")
            )
            is_template = vals.get(
                "is_template", self.env.context.get("default_is_template", False)
            )
            trusted_occurrence = self.env.su and vals.get("recurrence_id")
            if (
                project.agile_enabled
                and "agile_acceptance_criteria" in vals
                and not is_template
                and not trusted_occurrence
                and project._agile_role_for_user(self.env.user)
                not in ("manager", "contributor")
            ):
                raise AccessError(
                    _("Only Agile managers and contributors can set issue acceptance criteria.")
                )
            if project.agile_enabled and vals.get("recurring_task"):
                if is_template:
                    raise ValidationError(
                        _("Issue templates cannot be configured as recurring tasks.")
                    )
                if project._agile_role_for_user(self.env.user) not in (
                    "manager", "contributor"
                ):
                    raise AccessError(
                        _("Only Agile managers and contributors can create recurring issues.")
                    )
            if project.agile_enabled and is_template:
                if project._agile_role_for_user(self.env.user) != "manager":
                    raise AccessError(_("Only an Agile Manager can create issue templates."))
                vals["agile_issue"] = False
                vals["issue_key"] = False
                vals["sprint_id"] = False
                vals["recurring_task"] = False
        tasks = super().create(vals_list)
        return tasks

    def write(self, vals):
        agile_templates = self.filtered(
            lambda task: task.is_template and task.project_id.agile_enabled
        )
        if not self.env.su and any(
            not task.project_id.with_user(self.env.user).has_access("read")
            for task in agile_templates
        ):
            raise AccessError(
                _("You must retain native Odoo Project access to edit this template.")
            )
        if vals.get("is_template") is True:
            for task in self.filtered(lambda record: record.project_id.agile_enabled):
                if task.agile_issue:
                    raise ValidationError(
                        _("Save an Agile issue as a template to create a separate template; the issue identity must remain intact.")
                    )
                if task.project_id._agile_role_for_user(self.env.user) != "manager":
                    raise AccessError(_("Only an Agile Manager can create project issue templates."))
        recurrence_fields = {
            "recurring_task", "recurrence_id", "repeat_interval",
            "repeat_unit", "repeat_type", "repeat_until",
        }
        if recurrence_fields & vals.keys():
            if vals.get("recurring_task") and self.filtered(
                lambda task: task.project_id.agile_enabled and task.is_template
            ):
                raise ValidationError(
                    _("Create recurring issues from a reusable template, not by recurring the template itself.")
                )
            if self.filtered(
                lambda task: task.project_id.agile_enabled and task.is_template
            ):
                raise ValidationError(_("Recurring settings are not available on issue templates."))
            for task in self.filtered("agile_issue"):
                role = task.project_id._agile_role_for_user(self.env.user)
                if role not in ("manager", "contributor"):
                    raise AccessError(
                        _("Only Agile managers and contributors can change recurring issue settings.")
                    )
        if "agile_acceptance_criteria" in vals:
            for task in self.filtered(
                lambda record: record.project_id.agile_enabled
                and (record.agile_issue or record.is_template)
            ):
                role = task.project_id._agile_role_for_user(self.env.user)
                if role not in ("manager", "contributor") or (
                    task.is_template and role != "manager"
                ):
                    raise AccessError(
                        _("Only Agile managers and contributors can edit issue criteria; templates are manager-only.")
                    )
        if {"agile_task_type_id", "agile_component_id", "version_id"} & vals.keys():
            for task in self.filtered(
                lambda record: record.is_template and record.project_id.agile_enabled
            ):
                if task.project_id._agile_role_for_user(self.env.user) != "manager":
                    raise AccessError(_("Only an Agile Manager can configure issue templates."))
        if vals.get("is_template") is False and self.filtered(
            lambda task: task.project_id.agile_enabled and task.is_template
        ):
            raise ValidationError(
                _("Use Create from Template to make a new Agile issue.")
            )
        return super().write(vals)

    def action_convert_to_template(self):
        self.ensure_one()
        if not self.agile_issue:
            return super().action_convert_to_template()
        self._check_agile_manager_mutation()
        template = self.with_context(convert_to_template=True).copy({
            "name": self.name,
            "is_template": True,
            "agile_issue": False,
            "issue_key": False,
            "parent_id": False,
            "child_ids": [fields.Command.clear()],
            "sprint_id": False,
            "version_id": False,
            "recurrence_id": False,
            "recurring_task": False,
            "agile_blocked": False,
            "agile_block_reason": False,
            "agile_planned_start": False,
            "agile_planned_end": False,
            "depend_on_ids": False,
            "dependent_ids": False,
            "user_ids": [fields.Command.clear()],
        })
        return {
            "type": "ir.actions.act_window",
            "name": _("Agile Issue Template"),
            "res_model": "project.task",
            "res_id": template.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_undo_convert_to_template(self):
        if self.filtered(lambda task: task.project_id.agile_enabled and task.is_template):
            raise ValidationError(
                _("Agile templates are reusable starting points. Create an issue from the template instead.")
            )
        return super().action_undo_convert_to_template()

    def action_create_from_template(self, values=None):
        self.ensure_one()
        if self.project_id.agile_enabled and self.is_template:
            if not self.project_id.with_user(self.env.user).has_access("read"):
                raise AccessError(
                    _("You must retain native Odoo Project access to use this template.")
                )
            if self.project_id._agile_role_for_user(self.env.user) not in (
                "manager", "contributor"
            ):
                raise AccessError(_("Your Agile role cannot create an issue from a template."))
            backlog = self.project_id.type_ids.filtered(
                lambda stage: stage.active and stage.agile_status == "backlog"
            ).sorted(lambda stage: (not stage.agile_is_main, stage.sequence, stage.id))[:1]
            if not backlog:
                raise ValidationError(
                    _("Restore the project's Backlog stage before creating an issue from a template.")
                )
            values = dict(values or {})
            values.update({
                "project_id": self.project_id.id,
                "is_template": False,
                "agile_issue": True,
                "issue_key": False,
                "sprint_id": False,
                "recurrence_id": False,
                "recurring_task": False,
                "stage_id": backlog.id,
            })
        return super().action_create_from_template(values=values)

class AgileTaskRecurrence(models.Model):
    _inherit = "project.task.recurrence"

    def _check_agile_recurrence_edit_access(self):
        for task in self.mapped("task_ids").filtered("agile_issue"):
            if self.env.su:
                continue
            if not task.project_id.with_user(self.env.user).has_access("read"):
                raise AccessError(
                    _("You must retain native Odoo Project access to change recurring issues.")
                )
            if task.project_id._agile_role_for_user(self.env.user) not in (
                "manager", "contributor"
            ):
                raise AccessError(
                    _("Only Agile managers and contributors can change recurring issue settings.")
                )

    def write(self, vals):
        if not self.env.su:
            self._check_agile_recurrence_edit_access()
        return super().write(vals)

    def unlink(self):
        if not self.env.su:
            self._check_agile_recurrence_edit_access()
        return super().unlink()

    def _create_next_occurrences_values(self, recurrence_by_task):
        values_list = super()._create_next_occurrences_values(recurrence_by_task)
        for task, values in zip(recurrence_by_task, values_list):
            if task.agile_issue and task.project_id.agile_enabled:
                backlog = task.project_id.with_context(active_test=False).type_ids.filtered(
                    lambda stage: stage.active and stage.agile_status == "backlog"
                ).sorted(lambda stage: (not stage.agile_is_main, stage.sequence, stage.id))[:1]
                if not backlog:
                    raise ValidationError(
                        _("Restore the project's Backlog stage before generating recurring Agile issues.")
                    )
                values.update({
                    "project_id": task.project_id.id,
                    "is_template": False,
                    "agile_issue": True,
                    "issue_key": False,
                    "stage_id": backlog.id,
                    "state": "01_in_progress",
                    "sprint_id": False,
                    "parent_id": False,
                    "recurring_task": True,
                })
        return values_list
