from odoo import Command, api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


class AgileIssueMigrationWizard(models.TransientModel):
    _name = "agile_community.issue_migration_wizard"
    _description = "Prepare Existing Tasks for Agile"

    project_id = fields.Many2one("project.project", readonly=True)
    state = fields.Selection(
        [("draft", "Draft"), ("applying", "Applying"), ("done", "Done")],
        default="draft",
        readonly=True,
        copy=False,
    )
    task_ids = fields.Many2many(
        "project.task",
        string="Existing tasks",
        domain="[('project_id', '=', project_id)]",
        required=True,
    )
    issue_type_id = fields.Many2one(
        "agile_community.task_type",
        string="Default issue type",
        domain="[('active', '=', True), ('is_epic', '=', False), '|', ('project_ids', '=', False), ('project_ids', '=', project_id)]",
        required=True,
    )
    stage_mapping_ids = fields.One2many(
        "agile_community.issue_migration_stage",
        "wizard_id",
        string="Map existing stages",
    )
    task_count = fields.Integer(compute="_compute_preview")
    missing_key_count = fields.Integer(compute="_compute_preview")
    missing_type_count = fields.Integer(compute="_compute_preview")
    stages_to_map_count = fields.Integer(compute="_compute_preview")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals["state"] = "draft"
        return super().create(vals_list)

    def write(self, vals):
        if "state" in vals:
            raise AccessError(_("Conversion state is managed by the conversion action."))
        return super().write(vals)

    @api.model
    def default_get(self, names):
        values = super().default_get(names)
        tasks = self.env["project.task"].browse(
            self.env.context.get("active_ids", [])
        ).exists()
        projects = tasks.mapped("project_id")
        if len(projects) == 1:
            project = projects
            values["project_id"] = project.id
            backlog = self.env["project.task.type"].with_context(
                active_test=False
            ).search([
                ("project_ids", "=", project.id),
                ("agile_status", "=", "backlog"),
                ("active", "=", True),
            ], limit=1)
            if backlog:
                legacy_stages = tasks.mapped("stage_id").filtered(
                    lambda stage: not stage.agile_status
                )
                values["stage_mapping_ids"] = [
                    Command.create({
                        "source_stage_id": stage.id,
                        "target_stage_id": backlog.id,
                    })
                    for stage in legacy_stages
                ]
        if tasks:
            values["task_ids"] = [Command.set(tasks.ids)]
        return values

    @api.depends(
        "task_ids",
        "task_ids.issue_key",
        "task_ids.agile_task_type_id",
        "task_ids.stage_id",
    )
    def _compute_preview(self):
        for wizard in self:
            wizard.task_count = len(wizard.task_ids)
            wizard.missing_key_count = len(
                wizard.task_ids.filtered(lambda task: not task.issue_key)
            )
            wizard.missing_type_count = len(
                wizard.task_ids.filtered(lambda task: not task.agile_task_type_id)
            )
            wizard.stages_to_map_count = len(
                wizard.task_ids.mapped("stage_id").filtered(
                    lambda stage: not stage.agile_status
                )
            )

    @api.onchange("task_ids")
    def _onchange_task_ids(self):
        projects = self.task_ids.mapped("project_id")
        self.project_id = projects if len(projects) == 1 else False
        mapped = {
            line.source_stage_id.id: line.target_stage_id.id
            for line in self.stage_mapping_ids
        }
        legacy_stages = self.task_ids.mapped("stage_id").filtered(
            lambda stage: not stage.agile_status
        )
        backlog = self.env["project.task.type"].with_context(
            active_test=False
        ).search([
            ("project_ids", "=", self.project_id.id),
            ("agile_status", "=", "backlog"),
            ("active", "=", True),
        ], limit=1) if self.project_id else self.env["project.task.type"]
        self.stage_mapping_ids = [
            Command.create({
                "source_stage_id": stage.id,
                "target_stage_id": mapped.get(stage.id) or backlog.id or False,
            })
            for stage in legacy_stages
        ]

    def _check_project_manager(self):
        self.ensure_one()
        if (
            not self.project_id
            or not self.project_id.agile_enabled
        ):
            raise AccessError(
                _("Only this Agile project's manager can convert existing tasks.")
            )
        if not self.project_id.with_user(self.env.user).has_access("read"):
            raise AccessError(
                _("You must retain native Odoo Project access to convert its tasks.")
            )
        if self.project_id._agile_role_for_user(self.env.user) != "manager":
            raise AccessError(
                _("Only this Agile project's manager can convert existing tasks.")
            )
        if not self.task_ids or any(
            task.project_id != self.project_id for task in self.task_ids
        ):
            raise ValidationError(
                _("Select tasks from one Agile project only.")
            )

    def action_convert(self):
        self.ensure_one()
        self._check_project_manager()
        if self.state != "draft":
            raise ValidationError(_("This conversion has already been applied."))
        if self.task_ids.filtered("agile_issue"):
            raise ValidationError(
                _("Select native tasks only. Agile issues do not need conversion.")
            )
        if not self.issue_type_id or not self.issue_type_id.active:
            raise ValidationError(_("Choose an active default issue type."))
        if self.issue_type_id.is_epic:
            raise ValidationError(
                _("Choose a standard issue type. Existing tasks are not automatically converted to Epics.")
            )
        stage_targets = {}
        for line in self.stage_mapping_ids:
            target = line.target_stage_id
            if (
                not target
                or not target.active
                or target.project_ids != self.project_id
                or not target.agile_status
            ):
                raise ValidationError(
                    _("Map every existing stage to an active Agile stage in this project.")
                )
            stage_targets[line.source_stage_id.id] = target
        tasks = self.task_ids
        missing_stages = tasks.mapped("stage_id").filtered(
            lambda stage: not stage.agile_status and stage.id not in stage_targets
        )
        if missing_stages:
            raise ValidationError(
                _("Map every existing stage before converting the selected tasks.")
            )
        if tasks.filtered(
            lambda task: task.issue_key
            and not task.issue_key.startswith(f"{self.project_id.agile_key}-")
        ):
            raise ValidationError(
                _("A selected task already has a key outside this project. Resolve it before conversion.")
            )

        task_model = self.env["project.task"]
        converted = len(tasks)
        with self.env.cr.savepoint():
            super(AgileIssueMigrationWizard, self).write({"state": "applying"})
            for task in tasks:
                values = {
                    "agile_issue": True,
                    "issue_key": task.issue_key or task_model._allocate_key(self.project_id),
                    "agile_task_type_id": task.agile_task_type_id.id or self.issue_type_id.id,
                    "stage_id": (
                        task.stage_id.id
                        if task.stage_id.agile_status
                        else stage_targets[task.stage_id.id].id
                    ),
                }
                task.with_context(
                    agile_issue_conversion_wizard_id=self.id,
                ).write(values)
            super(AgileIssueMigrationWizard, self).write({"state": "done"})
        self.project_id.message_post(
            body=_("Agile conversion applied to %(count)s selected task(s).", count=converted),
            subtype_xmlid="mail.mt_note",
        )
        return {
            "type": "ir.actions.act_window",
            "name": _("Converted Agile issues"),
            "res_model": "project.task",
            "view_mode": "list,kanban,form,activity",
            "domain": [("id", "in", tasks.ids)],
            "context": {"default_project_id": self.project_id.id},
        }


class AgileIssueMigrationStage(models.TransientModel):
    _name = "agile_community.issue_migration_stage"
    _description = "Existing-to-Agile Stage Mapping"
    _order = "source_stage_id"

    wizard_id = fields.Many2one(
        "agile_community.issue_migration_wizard", required=True, ondelete="cascade"
    )
    source_stage_id = fields.Many2one("project.task.type", required=True, readonly=True)
    target_stage_id = fields.Many2one(
        "project.task.type",
        string="Move to Agile stage",
        required=True,
        domain="[('project_ids', '=', parent.project_id), ('agile_status', '!=', False), ('active', '=', True)]",
    )
