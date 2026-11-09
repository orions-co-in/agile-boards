import json

from odoo import Command, api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import is_html_empty

# The buttons and the (from, to) status pairs of the workflow moves each one stands for.
AGILE_BUTTON_MOVES = {
    "mark_ready": {("backlog", "ready")},
    "start": {("ready", "progress")},
    "send_review": {("progress", "review")},
    "return": {("review", "progress")},
    "complete": {("review", "done")},
    "reopen": {("done", "progress"), ("canceled", "backlog")},
    "cancel": {(source, "canceled") for source in ("backlog", "ready", "progress", "review")},
}


class AgileTaskType(models.Model):
    _name = "agile_community.task_type"
    _description = "Agile Issue Type"
    _order = "sequence, name"

    name = fields.Char(string="Name", required=True, translate=True)
    description = fields.Text(string="Description", translate=True)
    color = fields.Integer(string="Color", default=0)
    sequence = fields.Integer(default=10)
    is_epic = fields.Boolean(
        string="Epic type",
        help="Epic issues organize standard issues and cannot be subtasks.",
    )
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", string="Company", default=lambda self: self.env.company
    )
    project_ids = fields.Many2many(
        "project.project",
        "agile_task_type_project_rel",
        "type_id",
        "project_id",
        string="Projects",
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]",
    )

    _task_type_name_unique = models.Constraint(
        "unique (name, company_id, active)",
        "Issue type name must be unique.",
    )

    def _agile_project_ids_from_commands(self, commands, current_ids=None):
        """Resolve supported project_ids commands for scoped manager edits."""
        project_ids = set(current_ids or [])
        for command in commands or []:
            operation = command[0]
            if operation == 6:
                project_ids = set(command[2])
            elif operation == 4:
                project_ids.add(command[1])
            elif operation in (2, 3):
                project_ids.discard(command[1])
            elif operation == 5:
                project_ids.clear()
            elif operation == 0:
                raise ValidationError(
                    _("Create the Agile project before adding it to an issue type.")
                )
        return project_ids

    def _agile_check_type_configuration_access(self, project_ids):
        if not project_ids:
            if self.env.user.has_group("base.group_system"):
                return
            raise AccessError(
                _("Only an Odoo Administrator can edit issue types shared globally.")
            )
        projects = self.env["project.project"].browse(list(project_ids)).exists()
        if set(projects.ids) != set(project_ids) or any(
            not project.with_user(self.env.user).has_access("read")
            for project in projects
        ):
            raise AccessError(
                _("You must be able to open each Odoo Project to configure its issue types.")
            )
        if self.env.user.has_group("base.group_system"):
            return
        if any(
            not project.agile_enabled
            or project._agile_role_for_user(self.env.user) != "manager"
            for project in projects
        ):
            raise AccessError(
                _("Only an Agile Manager can edit issue types for their project.")
            )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            project_commands = vals.get("project_ids")
            if project_commands is None:
                project_commands = self.default_get(["project_ids"]).get(
                    "project_ids", []
                )
            project_ids = self._agile_project_ids_from_commands(
                project_commands
            )
            self._agile_check_type_configuration_access(project_ids)
        return super().create(vals_list)

    def write(self, vals):
        for record in self:
            current_project_ids = set(record.project_ids.ids)
            self._agile_check_type_configuration_access(current_project_ids)
            if "project_ids" in vals:
                project_ids = self._agile_project_ids_from_commands(
                    vals["project_ids"], current_project_ids
                )
                self._agile_check_type_configuration_access(project_ids)
        return super().write(vals)

    @api.constrains("project_ids", "company_id")
    def _check_project_companies(self):
        for issue_type in self:
            if issue_type.company_id and any(
                project.company_id
                and project.company_id != issue_type.company_id
                for project in issue_type.project_ids
            ):
                raise ValidationError(
                    _("An issue type and its projects must belong to the same company, or the type must be shared.")
                )

    def unlink(self):
        for issue_type in self:
            self._agile_check_type_configuration_access(
                set(issue_type.project_ids.ids)
            )
        # Archived issues and issues this person cannot see count too (E2E-001): the database would refuse the delete.
        referenced = self.env["project.task"].sudo().with_context(active_test=False).search_count([
            ("agile_task_type_id", "in", self.ids),
        ])
        if referenced:
            raise ValidationError(
                _("An issue type that is used by an issue must be archived instead of deleted.")
            )
        return super().unlink()

    @api.constrains("is_epic")
    def _check_epic_type_hierarchy(self):
        tasks = self.env["project.task"].search([
            ("agile_task_type_id", "in", self.ids),
        ])
        tasks._check_agile_parent_hierarchy()


class ProjectTask(models.Model):
    _inherit = "project.task"
    _rec_names_search = ["issue_key", "name", "agile_old_key_ids.key"]

    @api.model
    def _read_group_stage_ids(self, stages, domain):
        """Keep every workflow column on the board.

        Core stops adding the project's empty stages when the sub-task flag is set,
        which Agile projects set so that epic children stay visible.
        """
        context = self.env.context
        project_id = context.get("default_project_id")
        if context.get("agile_project_view") and project_id:
            stage_ids = stages._search(
                ["|", ("project_ids", "=", project_id), ("id", "in", stages.ids)],
                order=stages._order,
            )
            columns = stages.browse(stage_ids)
            if context.get("agile_scrum_mode"):
                # Jira-style sprint board (B-401, B-402): the backlog is its own screen
                # and canceled issues show only when asked for.
                hidden = {"backlog"}
                if not context.get("agile_show_canceled"):
                    hidden.add("canceled")
                columns = columns.filtered(lambda stage: stage.agile_status not in hidden)
            elif context.get("agile_hide_backlog_column"):
                # A Kanban board without its own Backlog column hides the empty one (OI-1).
                columns = columns.filtered(lambda stage: stage.agile_status != "backlog")
            return columns
        return super()._read_group_stage_ids(stages, domain)

    @api.model
    def get_empty_list_help(self, help_message):
        """Customize Agile task empty states without changing normal Project."""
        help_message = super().get_empty_list_help(help_message)
        project_id = self.env.context.get("default_project_id")
        project = self.env["project.project"].browse(project_id).exists()
        if project and project.agile_enabled:
            issue_count = self.search_count(
                [("project_id", "=", project.id), ("agile_issue", "=", True)]
            )
            if self.env.context.get("agile_unconverted_list"):
                return _(
                    '<p class="o_view_nocontent_smiling_face">'
                    "Nothing to convert."
                    "</p><p>This project has no existing tasks waiting to become "
                    "Agile issues. Create issues from the <strong>Backlog</strong>, "
                    "or import them from <strong>Settings</strong>."
                    "</p>"
                )
            if project._agile_role_for_user() == "none":
                return _(
                    '<p class="o_view_nocontent_smiling_face">'
                    "You are not on this project's Agile team."
                    "</p><p>Ask a project manager to add you from <strong>Team and roles</strong> "
                    "in the project settings. Existing Project tasks stay unchanged until a "
                    "manager prepares them."
                    "</p>"
                )
            if not issue_count and project._agile_role_for_user() == "manager":
                return _(
                    '<p class="o_view_nocontent_smiling_face">'
                    "No issues yet."
                    "</p><p>Create the first issue from the <strong>Backlog</strong>, "
                    "or import existing work from <strong>Settings</strong>."
                    "</p>"
                )
            if not issue_count:
                return _(
                    '<p class="o_view_nocontent_smiling_face">'
                    "No Agile issues are available here yet."
                    "</p><p>If this is a new project, select <strong>New</strong> "
                    "if your role allows it. If you expected existing work, ask the "
                    "project manager to confirm your Agile team access. "
                    "Existing Project tasks stay unchanged until a manager prepares them."
                    "</p>"
                )
            if (
                self.env.context.get("agile_scrum_mode")
                and not project.agile_current_sprint_id
            ):
                return _(
                    '<p class="o_view_nocontent_smiling_face">'
                    "No sprint is active."
                    "</p><p>The board shows the active sprint. Open the "
                    "<strong>Backlog</strong> from the sidebar, move issues into a "
                    "sprint and choose <strong>Start sprint</strong>."
                    "</p>"
                )
            if (
                project.agile_method != "scrum"
                and not project.agile_kanban_backlog_column
                and self.env.context.get("agile_project_view")
            ):
                waiting = self.search_count([
                    ("project_id", "=", project.id), ("agile_issue", "=", True),
                    ("stage_id.agile_status", "=", "backlog"),
                ])
                on_board = self.search_count([
                    ("project_id", "=", project.id), ("agile_issue", "=", True),
                    ("stage_id.agile_status", "!=", "backlog"),
                ])
                if waiting and not on_board:
                    return _(
                        '<p class="o_view_nocontent_smiling_face">'
                        "Nothing is on the board yet."
                        "</p><p>%s issues are waiting in the <strong>Backlog</strong>. "
                        "Open it from the sidebar and move the ones you want to work on "
                        "to <strong>To Do</strong>.</p>",
                        waiting,
                    )
            return _(
                '<p class="o_view_nocontent_smiling_face">'
                "No issues match the filters on this board."
                "</p><p>For example, <strong>Mine</strong> shows only issues assigned to you. "
                "Turn a filter off above to bring the columns back, "
                "or ask your project manager for access to create an issue.</p>"
            )
        return help_message

    def action_archive(self):
        """Archive Agile Epics without Odoo's native subtask cascade."""
        agile_epics = self.filtered(lambda task: task.agile_issue and task.agile_is_epic)
        if self.filtered("agile_issue"):
            self._check_agile_manager_mutation()
        other_tasks = self - agile_epics
        if agile_epics:
            agile_epics.write({"active": False})
        if other_tasks:
            super(ProjectTask, other_tasks).action_archive()
        return True

    agile_project_enabled = fields.Boolean(
        related="project_id.agile_enabled", export_string_translation=False
    )
    agile_use_scrum = fields.Boolean(
        related="project_id.use_scrum", export_string_translation=False
    )
    agile_issue = fields.Boolean(
        string="Agile issue",
        copy=False,
        index=True,
        readonly=True,
        tracking=True,
        help="Set only for newly created issues or tasks explicitly converted to Agile.",
    )
    retro_sprint_id = fields.Many2one(
        "project.sprint",
        string="Retrospective of",
        copy=False,
        index="btree_not_null",
        ondelete="set null",
        help="The sprint whose retrospective created this action.",
    )
    agile_planned_start = fields.Date(
        string="Planned start",
        copy=False,
        index=True,
        tracking=True,
        help="Optional roadmap start. Agile does not infer this from assignment or rank.",
    )
    agile_planned_end = fields.Date(
        string="Planned end",
        copy=False,
        index=True,
        tracking=True,
        help="Optional roadmap end. Agile does not infer this from completion or rank.",
    )
    agile_key = fields.Char(
        related="project_id.agile_key", export_string_translation=False
    )
    issue_key = fields.Char(
        string="Issue Key",
        copy=False,
        index=True,
        tracking=True,
    )
    parent_issue_key = fields.Char(
        string="Parent Issue Key",
        compute="_compute_parent_issue_key",
        inverse="_inverse_parent_issue_key",
        help="For imports and exports, use the visible issue key of a parent in this project.",
    )
    agile_task_type_id = fields.Many2one(
        "agile_community.task_type",
        string="Issue Type",
        domain="[('active', '=', True), '|', ('project_ids', '=', False), ('project_ids', '=', project_id)]",
        ondelete="restrict",
        tracking=True,
    )
    agile_component_id = fields.Many2one(
        "agile.project.component",
        string="Component",
        ondelete="restrict",
        tracking=True,
        domain="[('project_id', '=', project_id)]",
        help="Optional project area that owns or groups this issue.",
    )
    agile_affects_version_ids = fields.Many2many(
        "project.version",
        "agile_task_affects_version_rel",
        "task_id",
        "version_id",
        string="Affects Versions",
        domain="[('project_id', '=', project_id)]",
        help="The releases this issue was found in. The Fix Version says where it is fixed.",
    )
    agile_task_type_color = fields.Integer(
        related="agile_task_type_id.color",
        export_string_translation=False,
    )
    agile_is_epic = fields.Boolean(related="agile_task_type_id.is_epic")
    agile_related_issue_ids = fields.Many2many(
        "project.task",
        compute="_compute_agile_issue_links",
        inverse="_inverse_agile_related_issues",
        string="Relates to",
        domain="[('id', '!=', id), ('agile_issue', '=', True)]",
    )
    agile_duplicate_issue_ids = fields.Many2many(
        "project.task",
        compute="_compute_agile_issue_links",
        inverse="_inverse_agile_duplicate_issues",
        string="Duplicates",
        domain="[('id', '!=', id), ('agile_issue', '=', True)]",
    )
    agile_child_issue_count = fields.Integer(
        string="Child issues", compute="_compute_agile_child_summary"
    )
    agile_child_done_count = fields.Integer(
        string="Completed children", compute="_compute_agile_child_summary"
    )
    agile_child_points = fields.Float(
        string="Estimated child points", compute="_compute_agile_child_summary",
        digits=(16, 2),
    )
    agile_child_unestimated_count = fields.Integer(
        string="Unestimated children", compute="_compute_agile_child_summary"
    )
    agile_status = fields.Selection(
        related="stage_id.agile_status",
        string="Agile Status",
        readonly=True,
    )
    agile_blocked = fields.Boolean(
        string="Mark as blocked",
        help="Use this for a blocker that is not tracked as a task dependency.",
        tracking=True,
        copy=False,
    )
    agile_block_reason = fields.Char(
        string="Block reason",
        help="Briefly explain what is preventing this issue from moving forward.",
        tracking=True,
        copy=False,
    )
    agile_flagged = fields.Boolean(
        string="Flagged",
        help="Marks an issue that needs a look. It does not change the status and is not a blocker.",
        copy=False,
        index=True,
    )
    agile_flag_note = fields.Char(
        string="Flag note",
        help="Optional: why this issue needs a look.",
        size=140,
        copy=False,
    )
    agile_is_blocked = fields.Boolean(
        string="Blocked",
        compute="_compute_agile_is_blocked",
        store=True,
    )
    agile_block_reason_display = fields.Char(
        compute="_compute_agile_is_blocked",
        store=True,
    )
    agile_blocked_by_text = fields.Char(
        string="Blocked by",
        compute="_compute_agile_blocked_by_text",
        help="Keys of the open issues this one waits for; shown as a tag on the Backlog and the Board.",
    )
    can_agile_update_block = fields.Boolean(compute="_compute_agile_actions")
    can_agile_mark_ready = fields.Boolean(compute="_compute_agile_actions")
    can_agile_start = fields.Boolean(compute="_compute_agile_actions")
    can_agile_send_review = fields.Boolean(compute="_compute_agile_actions")
    can_agile_return = fields.Boolean(compute="_compute_agile_actions")
    can_agile_complete = fields.Boolean(compute="_compute_agile_actions")
    can_agile_reopen = fields.Boolean(compute="_compute_agile_actions")
    can_agile_cancel = fields.Boolean(compute="_compute_agile_actions")
    can_agile_reorder_backlog = fields.Boolean(
        compute="_compute_agile_reorder_backlog"
    )
    can_agile_plan_roadmap = fields.Boolean(compute="_compute_can_agile_plan_roadmap")
    can_agile_clone = fields.Boolean(compute="_compute_can_agile_clone")
    agile_custom_moves = fields.Char(
        compute="_compute_agile_custom_moves",
        help="JSON list of the workflow moves this user can take that no standard button covers (NU-08).",
    )
    can_agile_move_to = fields.Boolean(
        compute="_compute_can_agile_move_to", help="Whether the card's Move to… link is offered (E2E-012)."
    )
    can_agile_flag = fields.Boolean(
        compute="_compute_can_agile_move_to", help="Whether the Flag buttons are offered; stakeholders only read (NU-09)."
    )

    _issue_key_unique = models.Constraint(
        "unique (issue_key)",
        "Issue Key must be unique.",
    )

    @api.depends("agile_issue", "parent_id.issue_key")
    def _compute_parent_issue_key(self):
        for task in self:
            task.parent_issue_key = (
                task.parent_id.issue_key
                if task.agile_issue and task.parent_id.agile_issue
                else False
            )

    def _inverse_parent_issue_key(self):
        Task = self.env["project.task"]
        for task in self:
            key = (task.parent_issue_key or "").strip()
            if not key:
                if task.agile_issue:
                    task.parent_id = False
                continue
            if not task.agile_issue or not task.project_id.agile_enabled:
                raise ValidationError(
                    _("Parent Issue Key can only be set on an Agile issue.")
                )
            parent = Task.search(
                [
                    ("project_id", "=", task.project_id.id),
                    ("agile_issue", "=", True),
                    ("issue_key", "=", key),
                    ("active", "=", True),
                ],
                limit=1,
            )
            if not parent:
                raise ValidationError(
                    _("No accessible active issue with key %(key)s exists in this project.", key=key)
                )
            if parent == task:
                raise ValidationError(_("An issue cannot be its own parent."))
            parent.check_access("read")
            task.parent_id = parent

    def _agile_conversion_wizard_is_applying(self):
        wizard_id = self.env.context.get("agile_issue_conversion_wizard_id")
        if not isinstance(wizard_id, int) or wizard_id <= 0 or not self:
            return False
        wizard = self.env[
            "agile_community.issue_migration_wizard"
        ].sudo().browse(wizard_id).exists()
        if (
            not wizard
            or wizard.state != "applying"
            or any(task.project_id != wizard.project_id for task in self)
            or any(task not in wizard.task_ids for task in self)
            or not wizard.project_id.with_user(self.env.user).has_access("read")
            or wizard.project_id._agile_role_for_user(self.env.user) != "manager"
        ):
            return False
        return True

    def _agile_workflow_setup_is_authorized(self):
        return self.env.su or self._agile_conversion_wizard_is_applying()

    @api.constrains("agile_planned_start", "agile_planned_end", "agile_issue")
    def _check_agile_planned_dates(self):
        for task in self:
            if (task.agile_planned_start or task.agile_planned_end) and not task.agile_issue:
                raise ValidationError(
                    _("Only an Agile issue can have Agile roadmap dates.")
                )
            if (
                task.agile_planned_start
                and task.agile_planned_end
                and task.agile_planned_end < task.agile_planned_start
            ):
                raise ValidationError(
                    _("The planned end must be on or after the planned start.")
                )

    @api.model_create_multi
    def create(self, vals_list):
        agile_project_ids = sorted({
            vals.get("project_id") or self.env.context.get("default_project_id")
            for vals in vals_list
            if (vals.get("project_id") or self.env.context.get("default_project_id"))
            and not vals.get("is_template", self.env.context.get("default_is_template", False))
            and self.env["project.project"].browse(
                vals.get("project_id") or self.env.context.get("default_project_id")
            ).agile_enabled
        })
        next_backlog_sequence = {}
        for project_id in agile_project_ids:
            self.env.cr.execute(
                "SELECT pg_advisory_xact_lock(%s, %s)",
                (1095190871, project_id),
            )
            last_issue = self.search([
                ("project_id", "=", project_id),
                ("stage_id.agile_status", "=", "backlog"),
            ], order="sequence desc, id desc", limit=1)
            next_backlog_sequence[project_id] = (
                (last_issue.sequence if last_issue else 0) + 10
            )
        for vals in vals_list:
            project = self.env["project.project"].browse(
                vals.get("project_id") or self.env.context.get("default_project_id")
            )
            if vals.get("issue_key"):
                raise ValidationError(
                    _("Issue Keys are allocated automatically. Leave the field blank for new issues.")
                )
            if vals.get("agile_issue") and not project.agile_enabled:
                raise ValidationError(
                    _("Only an Agile-enabled project can create Agile issues.")
                )
            if {"agile_planned_start", "agile_planned_end"} & vals.keys():
                if not project.agile_enabled or not project._agile_allows("roadmap_dates"):
                    raise AccessError(
                        _("Only this project's Agile Manager can set roadmap dates.")
                    )
            if project.agile_enabled:
                if not self.env.su and not project.with_user(
                    self.env.user
                ).has_access("read"):
                    raise AccessError(
                        _("You must retain native Odoo Project access to create Agile issues here.")
                    )
                vals.setdefault("project_id", project.id)
                if not vals.get("is_template", self.env.context.get("default_is_template", False)):
                    vals["agile_issue"] = True
                    if not (self.env.su and vals.get("recurrence_id")):
                        self._check_agile_stakeholder_mutation(project=project)
            if project.agile_enabled and not vals.get("is_template", self.env.context.get("default_is_template", False)) and (
                "sequence" not in vals or self.env.context.get("copy_from_template")
            ):
                vals["sequence"] = next_backlog_sequence[project.id]
                next_backlog_sequence[project.id] += 10
            if project.agile_enabled and not vals.get("agile_task_type_id"):
                # Honour a caller's default (e.g. the Epic list) before falling back to Task.
                vals["agile_task_type_id"] = self.env.context.get(
                    "default_agile_task_type_id"
                ) or self.env.ref("agile_community.agile_task_type_task").id
            self._check_agile_task_type_value(
                project, vals.get("agile_task_type_id")
            )
            if vals.get("agile_component_id"):
                self._check_agile_component_value(project, vals["agile_component_id"])
                component = self.env["agile.project.component"].browse(
                    vals["agile_component_id"]
                )
                if component.owner_id and not vals.get("user_ids"):
                    vals["user_ids"] = [Command.set([component.owner_id.id])]
            if project.agile_enabled and vals.get("version_id"):
                self._check_agile_version_value(project, vals["version_id"])
            if (
                project.agile_enabled
                and {"agile_blocked", "agile_block_reason"} & vals.keys()
            ):
                self._check_agile_block_permission(project=project)
                blocked = vals.get("agile_blocked", False)
                reason = vals.get("agile_block_reason", False)
                if blocked and not (reason or "").strip():
                    raise ValidationError(
                        _("Add a short reason before marking an issue as blocked.")
                    )
                if reason and not blocked:
                    raise ValidationError(
                        _("A block reason can only be saved while the issue is blocked.")
                    )
            if (
                vals.get("project_id")
                and not vals.get("is_template", self.env.context.get("default_is_template", False))
                and not vals.get("issue_key")
            ):
                project = self.env["project.project"].browse(vals["project_id"])
                if project.agile_enabled:
                    vals["issue_key"] = self._allocate_key(project)
                    backlog_stage = self.env["project.task.type"].with_context(
                        active_test=False
                    ).search([
                        ("project_ids", "=", project.id),
                        ("agile_status", "=", "backlog"),
                    ], limit=1)
                    if not backlog_stage:
                        raise ValidationError(
                            _("The Agile workflow is not configured for this project.")
                        )
                    if not backlog_stage.active:
                        raise ValidationError(
                            _(
                                "The Backlog stage is archived. Ask a project "
                                "manager to restore it before creating issues."
                            )
                        )
                    if vals.get("stage_id") and vals["stage_id"] != backlog_stage.id:
                        raise ValidationError(
                            _("New Agile issues must start in Backlog.")
                        )
                    vals["stage_id"] = backlog_stage.id
                    vals["state"] = "01_in_progress"
        tasks = super().create(vals_list)
        tasks._validate_agile_task_dependencies()
        tasks._agile_run_automation("created")
        return tasks

    @api.model
    def load(self, fields, data):
        """Allow safe updates by Issue Key through Odoo's native importer.

        Odoo's import mapper omits model-readonly fields, so Issue Key is
        read-only in every task view and immutable in ``write``, but is
        importable as an update locator. Resolve keys as the current user and
        let native ``load`` perform the write/access checks.
        """
        fields = list(fields)
        if "issue_key" not in fields:
            return super().load(fields, data)

        key_index = fields.index("issue_key")
        external_id_index = fields.index("id") if "id" in fields else None
        database_id_index = fields.index(".id") if ".id" in fields else None
        rows = [list(row) for row in data]
        if database_id_index is None:
            fields.append(".id")
            database_id_index = len(fields) - 1
            for row in rows:
                row.append("")

        errors = []
        row_keys = {}
        for row_index, row in enumerate(rows):
            issue_key = (row[key_index] or "").strip()
            external_id = row[external_id_index] if external_id_index is not None else ""
            database_id = row[database_id_index] if database_id_index is not None else ""
            if issue_key and not external_id and not database_id:
                row_keys.setdefault(issue_key, []).append(row_index)
        for issue_key, row_indexes in row_keys.items():
            if len(row_indexes) > 1:
                errors.extend(
                    {
                        "type": "error",
                        "record": row_index + 1,
                        "field": "issue_key",
                        "rows": {"from": row_index + 1, "to": row_index + 1},
                        "message": _("Each Issue Key may appear only once in an import file."),
                    }
                    for row_index in row_indexes
                )
        if errors:
            return {"ids": False, "messages": errors, "nextrow": 0}

        for issue_key, row_indexes in row_keys.items():
            row_index = row_indexes[0]
            task = self.search(
                [("issue_key", "=", issue_key), ("agile_issue", "=", True)],
                limit=1,
            )
            if not task:
                errors.append({
                    "type": "error",
                    "record": row_index + 1,
                    "field": "issue_key",
                    "rows": {"from": row_index + 1, "to": row_index + 1},
                    "message": _(
                        "No accessible active Agile issue matches this Issue Key. "
                        "Leave the key blank to create a new issue."
                    ),
                })
                continue
            rows[row_index][database_id_index] = str(task.id)

        if errors:
            return {"ids": False, "messages": errors, "nextrow": 0}
        return super().load(fields, rows)

    @api.depends_context("uid")
    def _compute_agile_issue_links(self):
        links = self.env["agile_community.issue_link"].sudo().search([
            "|", ("issue_a_id", "in", self.ids), ("issue_b_id", "in", self.ids),
        ])
        for task in self:
            related = self.env["project.task"]
            duplicates = self.env["project.task"]
            for link in links:
                if link.issue_a_id == task:
                    linked = link.issue_b_id
                elif link.issue_b_id == task:
                    linked = link.issue_a_id
                else:
                    continue
                if link.link_type == "relates":
                    related |= linked
                else:
                    duplicates |= linked
            task.agile_related_issue_ids = related.filtered(
                lambda issue: issue.with_user(self.env.user).has_access("read")
                and (
                    issue.project_id == task.project_id
                    or (
                        task.project_id.with_user(self.env.user).has_access("read")
                        and issue.project_id.with_user(self.env.user).has_access("read")
                    )
                )
            )
            task.agile_duplicate_issue_ids = duplicates.filtered(
                lambda issue: issue.with_user(self.env.user).has_access("read")
                and (
                    issue.project_id == task.project_id
                    or (
                        task.project_id.with_user(self.env.user).has_access("read")
                        and issue.project_id.with_user(self.env.user).has_access("read")
                    )
                )
            )

    def _agile_can_read_task_link(
        self, source, linked, project_read=None, allow_cross_project=True
    ):
        """Preserve native links unless either endpoint is an Agile issue."""
        if not source or not linked:
            return False
        source_is_agile = source.agile_issue and source.project_id.agile_enabled
        linked_is_agile = linked.agile_issue and linked.project_id.agile_enabled
        if not source_is_agile and not linked_is_agile:
            return True
        if source_is_agile != linked_is_agile:
            return False
        if not linked.with_user(self.env.user).has_access("read"):
            return False
        if source.project_id == linked.project_id:
            return True
        if not allow_cross_project:
            return False
        project_read = project_read if project_read is not None else {}
        for project in (source.project_id, linked.project_id):
            if project.id not in project_read:
                project_read[project.id] = project.with_user(
                    self.env.user
                ).has_access("read")
        return project_read[source.project_id.id] and project_read[linked.project_id.id]

    def read(self, fields=None, load="_classic_read"):
        values = super().read(fields=fields, load=load)
        relation_fields = {
            "parent_id", "child_ids", "depend_on_ids", "dependent_ids"
        }
        if fields is not None:
            relation_fields &= set(fields)
        if not relation_fields:
            return values

        source_records = self.sudo().browse(
            [row["id"] for row in values if row.get("id")]
        ).exists()
        source_by_id = {task.id: task for task in source_records}

        def relation_ids(row, field_name):
            value = row.get(field_name)
            if field_name == "parent_id":
                if not value:
                    return []
                return [value[0] if isinstance(value, (tuple, list)) else value]
            return value or []

        linked_ids = {
            linked_id
            for row in values
            for field_name in relation_fields
            for linked_id in relation_ids(row, field_name)
        }
        linked_records = self.sudo().browse(linked_ids).exists()
        linked_by_id = {task.id: task for task in linked_records}
        project_read = {}
        for row in values:
            source = source_by_id.get(row.get("id"))
            if not source:
                continue
            for field_name in relation_fields:
                if field_name == "parent_id" and row.get(field_name):
                    parent_value = row[field_name]
                    linked_id = (
                        parent_value[0]
                        if isinstance(parent_value, (tuple, list))
                        else parent_value
                    )
                    if not self._agile_can_read_task_link(
                        source,
                        linked_by_id.get(linked_id),
                        project_read,
                        allow_cross_project=False,
                    ):
                        row[field_name] = False
                elif field_name == "child_ids" and field_name in row:
                    row[field_name] = [
                        linked_id
                        for linked_id in row[field_name]
                        if self._agile_can_read_task_link(
                            source,
                            linked_by_id.get(linked_id),
                            project_read,
                            allow_cross_project=False,
                        )
                    ]
                elif field_name in ("depend_on_ids", "dependent_ids") and field_name in row:
                    row[field_name] = [
                        linked_id
                        for linked_id in row[field_name]
                        if self._agile_can_read_task_link(
                            source, linked_by_id.get(linked_id), project_read
                        )
                    ]
        return values

    def export_data(self, fields_to_export):
        sources = self.sudo().browse(self.ids).exists()
        agile_sources = sources.filtered("agile_issue")
        for source in agile_sources:
            if not source.with_user(self.env.user).has_access("read"):
                raise AccessError(_("You cannot export an issue you cannot view."))

        guarded_fields = {
            "parent_id", "child_ids", "depend_on_ids", "dependent_ids"
        }
        exported_fields = {path.split("/", 1)[0] for path in fields_to_export}
        selected_fields = guarded_fields & exported_fields
        if not selected_fields:
            return super().export_data(fields_to_export)

        # Check the full relation before native export reads it through the
        # viewer's filtered `read()` payload, which intentionally omits hidden
        # cross-project links.
        sources.invalidate_recordset(selected_fields)
        project_read = {}
        for source in sources:
            if selected_fields & {"parent_id", "child_ids"}:
                for linked in source.parent_id | source.child_ids:
                    if not self._agile_can_read_task_link(
                        source,
                        linked,
                        project_read,
                        allow_cross_project=False,
                    ):
                        raise AccessError(
                            _("You cannot export hierarchy records you cannot view.")
                        )
            if selected_fields & {"depend_on_ids", "dependent_ids"}:
                for linked in source.depend_on_ids | source.dependent_ids:
                    if not self._agile_can_read_task_link(
                        source, linked, project_read
                    ):
                        raise AccessError(
                            _("You cannot export dependencies that you cannot view.")
                        )
        return super().export_data(fields_to_export)

    def _inverse_agile_related_issues(self):
        for task in self:
            # Ordinary tasks have no relationships to store; do not reject them.
            if task.agile_issue or task.agile_related_issue_ids:
                task._sync_agile_issue_links("relates", task.agile_related_issue_ids)

    def _inverse_agile_duplicate_issues(self):
        for task in self:
            if task.agile_issue or task.agile_duplicate_issue_ids:
                task._sync_agile_issue_links("duplicates", task.agile_duplicate_issue_ids)

    def _check_agile_issue_link_permission(self):
        if self._agile_role() not in ("manager", "contributor"):
            raise AccessError(
                _("Only Agile managers and contributors can change issue links.")
            )

    def _validate_agile_task_dependencies(self, check_permission=True):
        """Validate the issue's blocker links.

        Changing a link needs the manager or contributor role, but saving an unrelated field (a
        reviewer finishing an issue that blocks another) must not, so writes pass False unless
        the links themselves were written.
        """
        for issue in self:
            pairs = [(issue, blocker) for blocker in issue.depend_on_ids]
            pairs += [(blocker, issue) for blocker in issue.dependent_ids]
            for source, target in pairs:
                if not (source.agile_issue or target.agile_issue):
                    continue
                if (
                    not source.agile_issue
                    or not target.agile_issue
                ):
                    raise ValidationError(
                        _("Agile blockers can only link to other Agile issues.")
                    )
                if source.company_id != target.company_id:
                    raise ValidationError(
                        _("Issues in different companies cannot be linked.")
                    )
                agile_issue = source if source.agile_issue else target
                if check_permission:
                    agile_issue._check_agile_issue_link_permission()
                if not source.with_user(self.env.user).has_access("read"):
                    raise AccessError(_("You cannot link an issue you cannot view."))
                if not target.with_user(self.env.user).has_access("read"):
                    raise AccessError(_("You cannot link an issue you cannot view."))
                if source.project_id != target.project_id and (
                    not source.project_id.with_user(self.env.user).has_access("read")
                    or not target.project_id.with_user(self.env.user).has_access("read")
                ):
                    raise AccessError(
                        _("Cross-project issue links require access to both Odoo Projects.")
                    )

    def _sync_agile_issue_links(self, link_type, linked_issues):
        self.ensure_one()
        if not self.agile_issue:
            raise ValidationError(
                _("Issue relationships are available only in Agile projects.")
            )
        self._check_agile_issue_link_permission()
        linked_issues = linked_issues.exists()
        if self in linked_issues:
            raise ValidationError(_("An issue cannot be linked to itself."))
        linked_issues.check_access("read")
        for linked in linked_issues:
            if not linked.agile_issue:
                raise ValidationError(
                    _("Only Agile issues can be linked to other Agile issues.")
                )
            if self.company_id != linked.company_id:
                raise ValidationError(
                    _("Issues in different companies cannot be linked.")
                )
            if linked.project_id != self.project_id and (
                not self.project_id.with_user(self.env.user).has_access("read")
                or not linked.project_id.with_user(self.env.user).has_access("read")
            ):
                raise AccessError(
                    _("Cross-project issue links require access to both Odoo Projects.")
                )

        Link = self.env["agile_community.issue_link"].sudo()
        current_links = Link.search([
            ("link_type", "=", link_type),
            "|", ("issue_a_id", "=", self.id), ("issue_b_id", "=", self.id),
        ])
        current_by_id = {
            (link.issue_b_id if link.issue_a_id == self else link.issue_a_id).id: link
            for link in current_links
        }
        desired_ids = set(linked_issues.ids)
        for target_id, link in current_by_id.items():
            target = self.browse(target_id).with_user(self.env.user)
            if target_id not in desired_ids and target.has_access("read"):
                link.unlink()
        for target in linked_issues:
            if target.id not in current_by_id:
                Link.create({
                    "issue_a_id": min(self.id, target.id),
                    "issue_b_id": max(self.id, target.id),
                    "link_type": link_type,
                })

    # ---- Links panel (I-1012): every link type, worded for the side being looked at ----

    @api.model
    def _agile_link_kinds(self):
        """Kind -> (label, stored as: a link_type, or 'blocks' for the dependency field)."""
        return {
            "blocked_by": (_("Is blocked by"), "blocks"),
            "blocks": (_("Blocks"), "blocks"),
            "clones": (_("Clones"), "clones"),
            "cloned_by": (_("Is cloned by"), "clones"),
            "duplicates": (_("Duplicates"), "duplicates"),
            "duplicated_by": (_("Is duplicated by"), "duplicates"),
            "duplicates_either": (_("Duplicates or is duplicated by"), "duplicates"),
            "relates": (_("Relates to"), "relates"),
        }

    def _agile_link_kind(self, link):
        """The wording of a link row seen from this issue."""
        if link.link_type == "relates":
            return "relates"
        if not link.source_id:
            return "duplicates_either"
        mine = link.source_id == self
        if link.link_type == "clones":
            return "clones" if mine else "cloned_by"
        return "duplicates" if mine else "duplicated_by"

    def _agile_link_item(self, kind, other, link=False):
        return {
            "kind": kind,
            "link_id": link.id if link else False,
            "id": other.id,
            "key": other.issue_key,
            "name": other.name,
            "status": other.agile_status,
            "status_label": dict(
                self.env["project.task.type"]._fields["agile_status"]._description_selection(self.env)
            ).get(other.agile_status, ""),
            "project": other.project_id.name,
        }

    def agile_links_data(self):
        """Grouped links for the Links panel, plus how many the user cannot see."""
        self.ensure_one()
        self.check_access("read")
        labels = self._agile_link_kinds()
        order = [
            "blocked_by", "blocks", "clones", "cloned_by",
            "duplicates", "duplicated_by", "duplicates_either", "relates",
        ]
        entries = [("blocked_by", blocker, False) for blocker in self.sudo().depend_on_ids]
        entries += [("blocks", blocked, False) for blocked in self.sudo().dependent_ids]
        for link in self.env["agile_community.issue_link"].sudo().search([
            "|", ("issue_a_id", "=", self.id), ("issue_b_id", "=", self.id),
        ]):
            other = link.issue_b_id if link.issue_a_id == self else link.issue_a_id
            entries.append((self._agile_link_kind(link), other, link))
        groups = {kind: [] for kind in order}
        hidden = 0
        project_read = {}
        for kind, other, link in entries:
            if not self._agile_can_read_task_link(self, other, project_read=project_read):
                hidden += 1
                continue
            groups[kind].append(self._agile_link_item(kind, other.with_user(self.env.user), link))
        return {
            "groups": [
                {"kind": kind, "label": labels[kind][0], "items": groups[kind]}
                for kind in order if groups[kind]
            ],
            "hidden": hidden,
            "can_edit": self._agile_role() in ("manager", "contributor"),
            "allow_blocking": bool(self.allow_task_dependencies),
        }

    def _agile_link_target(self, other_id):
        """Validate the issue on the other end of a link the user is about to change."""
        self.ensure_one()
        if not self.agile_issue:
            raise ValidationError(_("Issue relationships are available only in Agile projects."))
        self._check_agile_issue_link_permission()
        self.check_access("write")
        other = self.browse(other_id).exists()
        if not other or not other.with_user(self.env.user).has_access("read"):
            raise AccessError(_("You cannot link an issue you cannot view."))
        if other == self:
            raise ValidationError(_("An issue cannot be linked to itself."))
        return other

    def _agile_waits_for(self, issue):
        """True when `self` already waits, directly or through others, for `issue`."""
        seen, pending = set(), self.sudo().depend_on_ids
        while pending:
            if issue in pending:
                return True
            seen.update(pending.ids)
            pending = pending.depend_on_ids.filtered(lambda task: task.id not in seen)
        return False

    def _agile_already_linked_message(self, other, kind, kinds):
        return _(
            "%(key)s is already linked as %(kind)s. Remove that link first to change the type.",
            key=other.issue_key,
            kind=kinds[kind][0],
        )

    def agile_add_link(self, kind, other_id, ignore_existing=False):
        """Add a link of the given kind from this issue to another; returns the fresh panel data."""
        self.ensure_one()
        kinds = self._agile_link_kinds()
        if kind not in kinds or kind == "duplicates_either":
            raise ValidationError(_("Choose a link type."))
        other = self._agile_link_target(other_id)
        link_type = kinds[kind][1]
        if link_type == "blocks":
            if not self.allow_task_dependencies:
                raise ValidationError(_("Blocking links are switched off for this project."))
            blocker, blocked = (self, other) if kind == "blocks" else (other, self)
            if blocked in blocker.sudo().dependent_ids:
                if ignore_existing:
                    return self.agile_links_data()
                raise ValidationError(self._agile_already_linked_message(other, kind, kinds))
            if blocker._agile_waits_for(blocked):
                if blocker == other:
                    message = _(
                        "%(key)s already waits for this issue, so this link would make a loop.",
                        key=blocker.issue_key,
                    )
                else:
                    message = _(
                        "This issue already waits for %(key)s, so this link would make a loop.",
                        key=blocked.issue_key,
                    )
                raise ValidationError(message)
            blocked.write({"depend_on_ids": [Command.link(blocker.id)]})
        else:
            if not other.agile_issue:
                raise ValidationError(_("Only Agile issues can be linked to other Agile issues."))
            if self.company_id != other.company_id:
                raise ValidationError(_("Issues in different companies cannot be linked."))
            if other.project_id != self.project_id and not (
                self.project_id.with_user(self.env.user).has_access("read")
                and other.project_id.with_user(self.env.user).has_access("read")
            ):
                raise AccessError(_("Cross-project issue links require access to both Odoo Projects."))
            Link = self.env["agile_community.issue_link"].sudo()
            if Link.search_count([
                ("link_type", "=", link_type),
                ("issue_a_id", "=", min(self.id, other.id)),
                ("issue_b_id", "=", max(self.id, other.id)),
            ]):
                if ignore_existing:
                    return self.agile_links_data()
                raise ValidationError(self._agile_already_linked_message(other, kind, kinds))
            vals = {
                "issue_a_id": min(self.id, other.id),
                "issue_b_id": max(self.id, other.id),
                "link_type": link_type,
            }
            if link_type != "relates":
                source = self if kind in ("clones", "duplicates") else other
                vals["source_id"] = source.id
            Link.create(vals)
        (self | other)._agile_run_automation("link_added")
        return self.agile_links_data()

    def agile_remove_link(self, kind, other_id):
        """Remove a link of the given kind between this issue and another; returns the panel data."""
        self.ensure_one()
        kinds = self._agile_link_kinds()
        if kind not in kinds:
            raise ValidationError(_("Choose a link type."))
        other = self._agile_link_target(other_id)
        link_type = kinds[kind][1]
        if link_type == "blocks":
            blocker, blocked = (self, other) if kind == "blocks" else (other, self)
            blocked.write({"depend_on_ids": [Command.unlink(blocker.id)]})
        else:
            links = self.env["agile_community.issue_link"].sudo().search([
                ("link_type", "=", link_type),
                ("issue_a_id", "=", min(self.id, other.id)),
                ("issue_b_id", "=", max(self.id, other.id)),
            ]).filtered(lambda link: self._agile_link_kind(link) == kind)
            links.unlink()
        return self.agile_links_data()

    # ---- Clone (I-1014) ----

    def _agile_clone_values(self, project, stage):
        """What a clone takes from its original: never the key, history, time or comments."""
        self.ensure_one()
        return {
            "name": self.name,
            "description": self.description,
            "project_id": project.id,
            "stage_id": stage.id,
            "agile_task_type_id": self.agile_task_type_id.id,
            "agile_component_id": self.agile_component_id.id,
            # A finished release cannot take new issues, so the clone starts without it.
            "version_id": self.version_id.id if self.version_id.state != "released" else False,
            "story_points": self.story_points,
            "story_points_estimated": self.story_points_estimated,
            "priority": self.priority,
            "tag_ids": [Command.set(self.tag_ids.ids)],
            "parent_id": self.parent_id.id,
            "user_ids": [Command.clear()],
        }

    def _agile_copy_custom_values(self, clone):
        """Hook: agile_pro copies project field values to the clone."""

    def _agile_automation_snapshot(self, vals):
        """Hook: what agile_pro compares after a write to fire its rules."""
        return None

    def _agile_automation_after_write(self, before):
        """Hook: agile_pro fires its rules for what changed."""

    def _agile_run_automation(self, trigger):
        """Hook: agile_pro runs the project's rules for this trigger."""

    def agile_clone(self, title=None, copy_subtasks=True, copy_attachments=False, same_sprint=False):
        """Clone this issue into the Backlog of its project and link the two with Clones."""
        self.ensure_one()
        if not self.agile_issue:
            raise ValidationError(_("Only Agile issues can be cloned."))
        self.check_access("read")
        if self._agile_role() not in ("manager", "contributor"):
            raise AccessError(_("You cannot create issues in this project."))
        title = (title or "").strip() or _("Clone of %s", self.name)
        backlog = self.project_id.type_ids.filtered(
            lambda stage: stage.active and stage.agile_status == "backlog"
        ).sorted(lambda stage: (not stage.agile_is_main, stage.sequence, stage.id))[:1]
        if not backlog:
            raise ValidationError(_("Restore the project's Backlog stage before cloning an issue."))
        values = self._agile_clone_values(self.project_id, backlog)
        values["name"] = title
        # An active or completed sprint keeps its commitment, so only a planned one is joined.
        if (
            same_sprint and self.sprint_id.state == "draft"
            and self.project_id._agile_allows("sprint_membership")
        ):
            values["sprint_id"] = self.sprint_id.id
        clone = self.create(values)
        self._agile_copy_custom_values(clone)
        if copy_attachments:
            for attachment in self.env["ir.attachment"].search([
                ("res_model", "=", "project.task"), ("res_id", "=", self.id),
            ]):
                attachment.copy({"res_id": clone.id})
        if copy_subtasks:
            for child in self.child_ids.filtered("agile_issue"):
                if not child.has_access("read"):
                    continue
                sub = self.create({
                    **child._agile_clone_values(self.project_id, backlog),
                    "parent_id": clone.id,
                })
                child._agile_copy_custom_values(sub)
                if copy_attachments:
                    for attachment in self.env["ir.attachment"].search([
                        ("res_model", "=", "project.task"), ("res_id", "=", child.id),
                    ]):
                        attachment.copy({"res_id": sub.id})
        self.env["agile_community.issue_link"].sudo().create({
            "issue_a_id": min(self.id, clone.id),
            "issue_b_id": max(self.id, clone.id),
            "link_type": "clones",
            "source_id": clone.id,
        })
        return {"id": clone.id, "key": clone.issue_key, "name": clone.name}

    @api.depends(
        "child_ids.agile_issue",
        "child_ids.agile_status",
        "child_ids.story_points",
        "child_ids.story_points_estimated",
        "child_ids.project_id.scrum_estimate_unit",
    )
    def _compute_agile_child_summary(self):
        for task in self:
            children = task.child_ids.filtered(
                lambda child: self._agile_can_read_task_link(
                    task, child, allow_cross_project=False
                )
            ).filtered("agile_issue")
            task.agile_child_issue_count = len(children)
            task.agile_child_done_count = len(
                children.filtered(lambda child: child.agile_status == "done")
            )
            task.agile_child_points = sum(
                child._scrum_estimate()[1]
                for child in children
                if child._scrum_estimate()[0] and child.agile_status != "canceled"
            )
            task.agile_child_unestimated_count = len(
                children.filtered(
                    lambda child: (
                        not child._scrum_estimate()[0]
                        and child.agile_status != "canceled"
                    )
                )
            )

    def _check_agile_parent_hierarchy(self):
        if self._has_cycle():
            raise ValidationError(
                _("Error! You cannot create a recursive hierarchy of tasks.")
            )
        tasks = self | self.mapped("child_ids")
        for child in tasks:
            parent = child.parent_id
            if not parent or not (
                child.agile_issue or parent.agile_issue
            ):
                continue
            if (
                not child.agile_issue
                or not parent.agile_issue
                or child.project_id != parent.project_id
            ):
                raise ValidationError(
                    _("An Agile issue and its parent must be in the same Agile project.")
                )
            if not child.agile_task_type_id or not parent.agile_task_type_id:
                raise ValidationError(_("Select an issue type before setting its parent."))
            if child.agile_task_type_id.is_epic:
                raise ValidationError(_("An Epic cannot be a subtask."))
            if parent.agile_task_type_id.is_epic:
                if parent.parent_id:
                    raise ValidationError(
                        _("An Epic cannot be nested under another issue.")
                    )
            elif parent.parent_id and not parent.parent_id.agile_task_type_id.is_epic:
                raise ValidationError(
                    _("Issue hierarchy supports an Epic, its issues, and one subtask level.")
                )
            elif parent.parent_id and parent.parent_id.parent_id:
                raise ValidationError(_("Issue subtasks cannot have their own subtasks."))

    @api.constrains("parent_id", "project_id", "agile_task_type_id")
    def _check_agile_parent_type(self):
        self._check_agile_parent_hierarchy()

    def write(self, vals):
        return self._write_agile_values(vals)

    def _write_agile_values(self, vals, allow_cancel_action=False):
        before = None
        if not self.env.context.get("agile_automation_skip"):
            before = self._agile_automation_snapshot(vals)
        flags_before = (
            {task.id: task.agile_flagged for task in self.filtered("agile_issue")}
            if "agile_flagged" in vals else {}
        )
        result = self._write_agile_values_checked(vals, allow_cancel_action)
        self._agile_automation_after_write(before)
        self._agile_log_flags(flags_before)
        return result

    def _agile_log_flags(self, flags_before):
        """One chatter line each time an issue is flagged or the flag is removed."""
        for task in self.filtered(lambda t: t.id in flags_before and t.agile_flagged != flags_before[t.id]):
            if task.agile_flagged:
                note = task.agile_flag_note
                body = (
                    _("%(user)s flagged this issue: \"%(note)s\"", user=self.env.user.name, note=note)
                    if note else _("%s flagged this issue.", self.env.user.name)
                )
            else:
                body = _("%s removed the flag.", self.env.user.name)
                if task.agile_flag_note:
                    task.sudo().agile_flag_note = False
            task.message_post(body=body, message_type="notification", subtype_xmlid="mail.mt_note")

    def action_agile_toggle_flag(self):
        """The Flag / Remove flag button: flips the flag; a flagged issue keeps its note until the flag is removed."""
        for task in self:
            task.write({"agile_flagged": not task.agile_flagged})
        return True

    def _write_agile_values_checked(self, vals, allow_cancel_action=False):
        if {"agile_planned_start", "agile_planned_end"} & vals.keys():
            if self.filtered(lambda task: not task.agile_issue):
                raise ValidationError(
                    _("Roadmap dates can only be changed on prepared Agile issues.")
                )
            for project in self.mapped("project_id"):
                if not project._agile_allows("roadmap_dates"):
                    raise AccessError(
                        _("Only this project's Agile Manager can change roadmap dates.")
                    )
        if "agile_issue" in vals:
            if vals["agile_issue"] and not self._agile_conversion_wizard_is_applying():
                raise AccessError(
                    _("Use the manager conversion flow to prepare an existing task for Agile.")
                )
            if vals["agile_issue"]:
                for task in self:
                    project = task.project_id
                    if (
                        not project.agile_enabled
                        or not project.with_user(self.env.user).has_access("read")
                        or project._agile_role_for_user(self.env.user) != "manager"
                    ):
                        raise AccessError(
                            _("Only a project-visible Agile Manager can convert its tasks.")
                        )
                    issue_key = vals.get("issue_key", task.issue_key)
                    issue_type_id = vals.get(
                        "agile_task_type_id", task.agile_task_type_id.id
                    )
                    stage_id = vals.get("stage_id", task.stage_id.id)
                    target_stage = self.env["project.task.type"].with_context(
                        active_test=False
                    ).browse(stage_id).exists()
                    if (
                        not issue_key
                        or not issue_key.startswith(f"{project.agile_key}-")
                        or not target_stage
                        or not target_stage.active
                        or target_stage not in project.with_context(
                            active_test=False
                        ).type_ids
                        or not target_stage.agile_status
                    ):
                        raise ValidationError(
                            _("Provide a project issue key and an active Agile stage before conversion.")
                        )
                    self._check_agile_task_type_value(project, issue_type_id)
            if not vals["agile_issue"] and self.filtered("agile_issue"):
                raise ValidationError(
                    _("An Agile issue cannot be converted back to a native task.")
                )
        agile_tasks = self.filtered("agile_issue")
        native_tasks = self - agile_tasks
        rank_before = {}
        if "sequence" in vals and agile_tasks:
            agile_tasks.invalidate_recordset(["sequence"])
            rank_before = {
                task.id: task.sequence
                for task in agile_tasks
                if task.sequence != vals["sequence"]
            }
        if agile_tasks and native_tasks and ({"stage_id", "state"} & vals.keys()):
            native_result = super(ProjectTask, native_tasks).write(vals)
            agile_result = agile_tasks.with_context(agile_automation_skip=True).write(vals)
            self._validate_agile_task_dependencies(check_permission=bool({"depend_on_ids", "dependent_ids"} & vals.keys()))
            return native_result and agile_result
        if agile_tasks:
            agile_tasks._check_agile_stakeholder_mutation()
            if "active" in vals:
                agile_tasks._check_agile_manager_mutation()
        if {"agile_blocked", "agile_block_reason"} & vals.keys():
            agile_block_tasks = self.filtered("agile_issue")
            if agile_block_tasks:
                agile_block_tasks._check_agile_block_permission()
                for task in agile_block_tasks:
                    blocked = vals.get("agile_blocked", task.agile_blocked)
                    reason = vals.get("agile_block_reason", task.agile_block_reason)
                    if blocked and not (reason or "").strip():
                        raise ValidationError(
                            _("Add a short reason before marking an issue as blocked.")
                        )
                    if (
                        "agile_block_reason" in vals
                        and reason
                        and not blocked
                    ):
                        raise ValidationError(
                            _(
                                "A block reason can only be saved while the issue is blocked."
                            )
                        )
            if vals.get("agile_blocked") is False and "agile_block_reason" not in vals:
                vals = {**vals, "agile_block_reason": False}
        if "issue_key" in vals:
            for task in self:
                if vals["issue_key"] == task.issue_key:
                    continue
                if not (
                    not task.issue_key
                    and vals["issue_key"]
                    and vals.get("agile_issue") is True
                    and task._agile_conversion_wizard_is_applying()
                ) and not self.env.context.get("agile_moving_project"):
                    raise ValidationError(
                        _("Issue Keys are immutable after allocation.")
                    )
        if "project_id" in vals:
            target = self.env["project.project"].browse(vals["project_id"])
            for task in self:
                if task.project_id != target and (
                    task.agile_issue or target.agile_enabled
                ) and not self.env.context.get("agile_moving_project"):
                    raise ValidationError(
                        _(
                            "Agile issues cannot be moved between projects. "
                            "A guided conversion flow will be provided separately."
                        )
                    )
        if "agile_task_type_id" in vals:
            for task in self:
                if (
                    task.project_id.agile_enabled
                    and not task.agile_issue
                    and not task.is_template
                    and not task._agile_conversion_wizard_is_applying()
                ):
                    raise ValidationError(
                        _("Prepare this existing task for Agile before assigning an issue type.")
                    )
                task._check_agile_task_type_value(
                    task.project_id, vals["agile_task_type_id"]
                )
        if "agile_component_id" in vals:
            for task in self:
                self._check_agile_component_value(
                    task.project_id,
                    vals["agile_component_id"],
                    existing_component=task.agile_component_id,
                )
            if vals["agile_component_id"] and not vals.get("user_ids"):
                component = self.env["agile.project.component"].browse(
                    vals["agile_component_id"]
                )
                unassigned = self.filtered(lambda task: not task.user_ids)
                if component.owner_id and unassigned:
                    with_owner = {**vals, "user_ids": [Command.set([component.owner_id.id])]}
                    if unassigned == self:
                        vals = with_owner
                    else:
                        # Only the issues without an assignee get the component's default.
                        (self - unassigned).write(vals)
                        return unassigned.write(with_owner)
        if "version_id" in vals:
            for task in self.filtered(
                lambda record: record.agile_issue
                or (record.is_template and record.project_id.agile_enabled)
            ):
                self._check_agile_version_value(
                    task.project_id,
                    vals["version_id"],
                    existing_version=task.version_id,
                )
        transitions = []
        if "stage_id" in vals and vals["stage_id"]:
            target_stage = self.env["project.task.type"].with_context(
                active_test=False
            ).browse(vals["stage_id"])
            for task in agile_tasks:
                if target_stage not in task.project_id.with_context(
                    active_test=False
                ).type_ids:
                    raise ValidationError(
                        _("The selected stage does not belong to this project.")
                    )
                if not target_stage.agile_status:
                    raise ValidationError(
                        _("Agile issues must use a configured Agile workflow stage.")
                    )
                if not target_stage.active:
                    raise UserError(
                        _(
                            "This workflow stage is archived. Ask a project "
                            "manager to restore it before moving issues into it."
                        )
                    )
                if task.stage_id != target_stage:
                    workflow_setup = self._agile_workflow_setup_is_authorized()
                    if not workflow_setup:
                        if target_stage.agile_status == "canceled" and not allow_cancel_action:
                            raise UserError(
                                _(
                                    "Cancel an issue from its detail page using "
                                    "the Cancel Issue action."
                                )
                            )
                        task._check_agile_transition(target_stage.agile_status, target_stage)
                    transitions.append((task, task.stage_id, target_stage))
            if agile_tasks:
                vals = {
                    **vals,
                    "state": self._agile_state_for_status(
                        target_stage.agile_status
                    ),
                }
        elif (
            "state" in vals
            and agile_tasks
            and not self._agile_workflow_setup_is_authorized()
        ):
            if any(
                vals["state"] != task._agile_state_for_status(task.agile_status)
                for task in agile_tasks
            ):
                raise UserError(
                    _(
                        "Move this Agile issue to a workflow stage instead of "
                        "changing its task state directly."
                    )
                )
        if transitions and not self._agile_workflow_setup_is_authorized():
            with self.env.cr.savepoint():
                result = super().write(vals)
                self._validate_agile_task_dependencies(check_permission=bool({"depend_on_ids", "dependent_ids"} & vals.keys()))
                for task, source_stage, target_stage in transitions:
                    task._check_agile_transition_required_fields(
                        target_stage.agile_status, source_stage, target_stage
                    )
                self._record_agile_metric_transitions(transitions)
                self._agile_apply_resolution(transitions)
                self._record_agile_rank_changes(rank_before)
                return result
        result = super().write(vals)
        self._validate_agile_task_dependencies(check_permission=bool({"depend_on_ids", "dependent_ids"} & vals.keys()))
        if transitions and not self._agile_workflow_setup_is_authorized():
            self._record_agile_metric_transitions(transitions)
            self._agile_apply_resolution(transitions)
        self._record_agile_rank_changes(rank_before)
        return result

    def _record_agile_rank_changes(self, rank_before):
        """Keep a human-readable, actor/timestamp-stamped rank audit in chatter."""
        if not rank_before:
            return
        note_type = self.env.ref("mail.mt_note")
        tasks = self.browse(rank_before).exists()
        for task in tasks:
            old_rank = rank_before[task.id]
            if old_rank == task.sequence:
                continue
            task.message_post(
                body=_(
                    "Backlog rank changed from %(old)s to %(new)s.",
                    old=old_rank,
                    new=task.sequence,
                ),
                message_type="comment",
                subtype_id=note_type.id,
            )

    def _record_agile_metric_transitions(self, transitions):
        event_model = self.env["agile.issue.metric.event"]
        for task, _source_stage, target_stage in transitions:
            if target_stage.agile_status == "progress":
                event_model._record_first_transition(task, "started")
            elif target_stage.agile_status == "done":
                event_model._record_first_transition(task, "completed")

    @api.model
    def _check_agile_task_type_value(self, project, task_type_id):
        if not project:
            if task_type_id:
                raise ValidationError(
                    _("Issue Type can only be used on an Agile-enabled project.")
                )
            return
        if not project.agile_enabled:
            if task_type_id:
                raise ValidationError(
                    _("Issue Type can only be used on an Agile-enabled project.")
                )
            return
        if not task_type_id:
            raise ValidationError(_("Select an Issue Type for this Agile issue."))
        task_type = self.env["agile_community.task_type"].with_context(
            active_test=False
        ).browse(task_type_id).exists()
        if not task_type or not task_type.active:
            raise ValidationError(
                _("The selected Issue Type is archived or no longer available.")
            )
        if (
            task_type.company_id
            and project.company_id
            and task_type.company_id != project.company_id
        ):
            raise ValidationError(
                _("The selected Issue Type belongs to another company.")
            )
        if task_type.project_ids and project not in task_type.project_ids:
            raise ValidationError(
                _("The selected Issue Type is not available for this project.")
            )

    @api.model
    def _check_agile_component_value(
        self, project, component_id, existing_component=None
    ):
        if not component_id:
            return
        if not project or not project.agile_enabled:
            raise ValidationError(
                _("A component can only be assigned to an Agile issue.")
            )
        component = self.env["agile.project.component"].with_context(
            active_test=False
        ).browse(component_id).exists()
        if not component or component.project_id != project:
            raise ValidationError(
                _("Choose a component from the same Agile project.")
            )
        if not component.active and component != existing_component:
            raise ValidationError(
                _("Archived components remain on existing issues but cannot be newly assigned.")
            )

    @api.constrains("agile_affects_version_ids", "project_id")
    def _check_agile_affects_versions(self):
        for task in self:
            if task.agile_affects_version_ids.filtered(lambda version: version.project_id != task.project_id):
                raise ValidationError(_("Affects Versions must belong to the same project as the issue."))

    @api.model
    def _check_agile_version_value(
        self, project, version_id, existing_version=None
    ):
        if not version_id:
            return
        version = self.env["project.version"].with_context(
            active_test=False
        ).browse(version_id).exists()
        if not version or version.project_id != project:
            raise ValidationError(
                _("Fix Version must belong to the same project as the Agile issue.")
            )
        if not version.active and version != existing_version:
            raise ValidationError(
                _("Archived fix versions remain on existing issues but cannot be newly assigned.")
            )

    def unlink(self):
        if self.filtered("agile_issue"):
            self._check_agile_manager_mutation()
        Link = self.env["agile_community.issue_link"].sudo()
        links = Link.search([
            "|", ("issue_a_id", "in", self.ids), ("issue_b_id", "in", self.ids),
        ])
        linked_issues = (links.issue_a_id | links.issue_b_id) - self
        result = super().unlink()
        linked_issues.invalidate_recordset(
            ["agile_related_issue_ids", "agile_duplicate_issue_ids"]
        )
        return result

    @api.depends_context("uid")
    @api.depends(
        "agile_status",
        "stage_id",
        "agile_issue",
        "agile_task_type_id",
        "project_id.agile_member_ids.user_id",
        "project_id.agile_member_ids.role",
        "project_id.agile_workflow_ids.transition_ids.allow_contributor",
        "project_id.agile_workflow_ids.transition_ids.allow_reviewer",
        "project_id.agile_workflow_ids.transition_ids.allow_manager",
        "project_id.agile_workflow_ids.transition_ids.from_status_id",
        "project_id.agile_workflow_ids.transition_ids.to_status_id",
        "project_id.agile_workflow_ids.task_type_ids",
        "project_id.agile_permission_scheme",
        "project_id.agile_permission_custom",
    )
    def _compute_agile_actions(self):
        project_ids = self.filtered("agile_issue").mapped("project_id").ids
        roles_by_project = self._agile_roles_by_project(project_ids)
        for task in self:
            status = task.agile_status if task.agile_issue else False
            role = roles_by_project.get(task.project_id.id, "none")
            workflow_moves = task._agile_workflow_moves(role) if status else None
            if workflow_moves is not None:
                for name, pairs in AGILE_BUTTON_MOVES.items():
                    task[f"can_agile_{name}"] = bool(workflow_moves & pairs)
                task.can_agile_update_block = task.agile_issue and role in ("manager", "contributor")
                continue
            edges = task.project_id._agile_edges(role)
            is_member = role in ("manager", "contributor")
            task.can_agile_mark_ready = status == "backlog" and ("backlog", "ready") in edges
            task.can_agile_start = status == "ready" and ("ready", "progress") in edges
            task.can_agile_send_review = status == "progress" and ("progress", "review") in edges
            task.can_agile_return = status == "review" and ("review", "progress") in edges
            task.can_agile_complete = status == "review" and ("review", "done") in edges
            task.can_agile_reopen = status in ("done", "canceled") and (
                (status, "progress") in edges or (status, "backlog") in edges
            )
            task.can_agile_cancel = status in (
                "backlog", "ready", "progress", "review"
            ) and (status, "canceled") in edges
            task.can_agile_update_block = bool(task.agile_issue and is_member)

    @api.depends_context("uid")
    @api.depends(
        "sequence",
        "stage_id",
        "agile_issue",
        "project_id.agile_member_ids.user_id",
        "project_id.agile_member_ids.role",
    )
    def _compute_agile_reorder_backlog(self):
        for task in self:
            task.can_agile_reorder_backlog = False

        backlog_tasks = self.filtered(
            lambda task: task.agile_issue
            and task.agile_status == "backlog"
        )
        project_ids = backlog_tasks.mapped("project_id").ids
        if not project_ids:
            return
        roles_by_project = self._agile_roles_by_project(project_ids)
        ordered = self.with_context(active_test=False).search([
            ("project_id", "in", project_ids),
            ("stage_id.agile_status", "=", "backlog"),
            ("active", "=", True),
        ], order="project_id, sequence, id")
        counts_by_project = {}
        for task in ordered:
            counts_by_project[task.project_id.id] = (
                counts_by_project.get(task.project_id.id, 0) + 1
            )
        for task in backlog_tasks:
            task.can_agile_reorder_backlog = (
                counts_by_project.get(task.project_id.id, 0) > 1
                and roles_by_project.get(task.project_id.id)
                in ("manager", "contributor")
            )

    @api.depends_context("uid")
    @api.depends(
        "agile_issue",
        "project_id.agile_enabled",
        "project_id.agile_member_ids.user_id",
        "project_id.agile_member_ids.role",
    )
    def _compute_can_agile_plan_roadmap(self):
        for task in self:
            task.can_agile_plan_roadmap = bool(
                task.agile_issue
                and task.project_id.agile_enabled
                and task.project_id._agile_allows("roadmap_dates")
            )

    @api.depends_context("uid")
    @api.depends(
        "agile_issue",
        "project_id.agile_member_ids.user_id",
        "project_id.agile_member_ids.role",
    )
    def _compute_can_agile_clone(self):
        for task in self:
            task.can_agile_clone = bool(
                task.id and task.agile_issue
                and task._agile_role() in ("manager", "contributor")
            )

    @api.depends_context("uid")
    @api.depends(
        "agile_issue",
        "project_id.agile_member_ids.user_id",
        "project_id.agile_member_ids.role",
    )
    def _compute_can_agile_move_to(self):
        """Stakeholders (and people off the team) never move issues, so the phone card offers them no Move to…."""
        for task in self:
            task.can_agile_move_to = bool(
                task.id and task.agile_issue and task._agile_role() in ("manager", "contributor", "reviewer")
            )
            task.can_agile_flag = task.can_agile_move_to

    @api.depends_context("uid")
    @api.depends("stage_id", "agile_issue", "project_id.agile_member_ids.user_id", "project_id.agile_member_ids.role")
    def _compute_agile_custom_moves(self):
        for task in self:
            moves = task._agile_custom_moves() if task.id and task.agile_issue and task._agile_workflow() else []
            task.agile_custom_moves = json.dumps([{"id": move.id, "name": move.name} for move in moves]) if moves else False

    def _agile_custom_moves(self):
        """Moves the user may take from here that none of the standard buttons would take (NU-08).

        A standard button takes the first move from the stage to its category, so a second move to the
        same category, or a move that stays in the current category (Review to In QA), is custom.
        """
        self.ensure_one()
        allowed = self._agile_allowed_transitions().sorted(lambda move: (move.to_status_id.sequence, move.id))
        seen = set()
        custom = self.env["agile.workflow.transition"]
        source = self.stage_id
        current = self.agile_status
        for move in allowed:
            category = move.to_status_id.category
            if category != current and category not in seen:
                seen.add(category)
                continue
            custom |= move
        return custom.filtered(lambda move: move.from_status_id.stage_id == source)

    def action_agile_custom_move(self, transition_id):
        """Take one custom workflow move from the issue's current stage."""
        self.ensure_one()
        move = self._agile_custom_moves().filtered(lambda candidate: candidate.id == transition_id)
        if not move:
            raise UserError(_("That move is not available for this issue and your role."))
        self._write_agile_values({"stage_id": move.to_status_id.stage_id.id})
        return True

    def action_agile_open_clone(self):
        """Open the Clone dialog for this issue."""
        self.ensure_one()
        wizard = self.env["agile_community.clone_wizard"].create({"task_id": self.id})
        return {
            "type": "ir.actions.act_window",
            "name": _("Clone %s", self.issue_key or self.name),
            "res_model": wizard._name,
            "res_id": wizard.id,
            "view_mode": "form",
            "target": "new",
        }

    def _action_agile_move_backlog(self, direction):
        self.ensure_one()
        if not self.agile_issue or self.agile_status != "backlog":
            raise UserError(_("Only backlog issues can be reordered here."))
        if self._agile_role() not in ("manager", "contributor"):
            raise AccessError(_("Only Agile team members can reorder backlog issues."))

        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(%s, %s)",
            (1095190871, self.project_id.id),
        )
        ordered = self.with_context(active_test=False).search([
            ("project_id", "=", self.project_id.id),
            ("stage_id.agile_status", "=", "backlog"),
            ("active", "=", True),
        ], order="sequence, id")
        ordered.invalidate_recordset(["sequence"])
        issue_ids = ordered.ids
        index = issue_ids.index(self.id)
        target_index = index - 1 if direction == "up" else index + 1
        if target_index < 0 or target_index >= len(issue_ids):
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Backlog order unchanged"),
                    "message": _("This issue is already at that end of the backlog."),
                    "type": "info",
                    "sticky": False,
                },
            }

        issue_ids[index], issue_ids[target_index] = (
            issue_ids[target_index], issue_ids[index]
        )
        by_id = {task.id: task for task in ordered}
        for position, task_id in enumerate(issue_ids, start=1):
            by_id[task_id].write({"sequence": position * 10})
        return {"type": "ir.actions.client", "tag": "soft_reload"}

    def action_agile_move_backlog_up(self):
        return self._action_agile_move_backlog("up")

    def action_agile_move_backlog_down(self):
        return self._action_agile_move_backlog("down")

    def action_open_agile_bulk_update(self):
        """Open the bulk editor for the selected Agile issues only."""
        if not self:
            raise UserError(_("Select at least one Agile issue first."))
        errors = []
        for task in self:
            label = task.issue_key or task.display_name
            role = task._agile_role()
            if not task.agile_issue:
                errors.append(_("%s: this is not an Agile issue.") % label)
            elif role not in ("manager", "contributor"):
                errors.append(_("%s: only Agile team members can bulk edit issues.") % label)
            else:
                try:
                    task.check_access("write")
                except AccessError as error:
                    errors.append(_("%s: you cannot edit this issue (%s)") % (label, error))
        if errors:
            raise UserError(_("Bulk update was not opened:\n%s") % "\n".join(errors))
        return {
            "type": "ir.actions.act_window",
            "name": _("Bulk update issues"),
            "res_model": "agile_community.bulk_update_wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_task_ids": [Command.set(self.ids)]},
        }

    @api.model
    def _agile_state_for_status(self, status):
        return {
            "done": "1_done",
            "canceled": "1_canceled",
        }.get(status, "01_in_progress")

    def _agile_role(self, project=False):
        if not project:
            projects = self.mapped("project_id")
            if len(projects) != 1:
                return "none"
            project = projects
        return project._agile_role_for_user(self.env.user)

    @api.model
    def _agile_roles_by_project(self, project_ids):
        """Fetch the current user's Agile role for a project set in one query."""
        if not project_ids:
            return {}
        projects = self.env["project.project"].sudo().browse(project_ids)
        return {
            project_id: access[0]
            for project_id, access in projects._agile_access_by_project(self.env.user).items()
            if access[0] != "none"
        }

    @api.depends(
        "project_id.agile_enabled",
        "agile_blocked",
        "agile_block_reason",
        "allow_task_dependencies",
        "state",
    )
    def _compute_agile_is_blocked(self):
        for task in self:
            dependency_blocked = (
                task.agile_issue
                and task.allow_task_dependencies
                and task.state == "04_waiting_normal"
            )
            task.agile_is_blocked = bool(
                task.agile_issue
                and (task.agile_blocked or dependency_blocked)
            )
            task.agile_block_reason_display = (
                task.agile_block_reason
                if task.agile_blocked
                else _("Waiting for dependencies") if dependency_blocked else False
            )

    @api.depends("agile_issue", "depend_on_ids.issue_key", "depend_on_ids.stage_id.agile_status")
    def _compute_agile_blocked_by_text(self):
        for task in self:
            open_blockers = task.depend_on_ids.filtered(
                lambda b: b.agile_issue and b.active and b.agile_status not in ("done", "canceled") and b.has_access("read")
            ) if task.agile_issue else task.browse()
            keys = [b.issue_key for b in open_blockers.sorted("issue_key") if b.issue_key]
            task.agile_blocked_by_text = (
                keys[0] + (_(" and %d more", len(keys) - 1) if len(keys) > 1 else "")
                if keys else False
            )

    @api.constrains("agile_blocked", "agile_block_reason", "project_id")
    def _check_agile_block_reason(self):
        for task in self:
            if (
                task.agile_issue
                and task.agile_blocked
                and not (task.agile_block_reason or "").strip()
            ):
                raise ValidationError(
                    _("Add a short reason before marking an issue as blocked.")
                )

    def _check_agile_block_permission(self, project=False):
        tasks = self or self.browse()
        if tasks:
            denied = tasks.filtered(
                lambda task: task._agile_role() not in ("manager", "contributor")
            )
        else:
            denied = project and project._agile_role_for_user(self.env.user) not in (
                "manager", "contributor"
            )
        if denied:
            raise AccessError(_("Only Agile team members can change an issue's blocked status."))

    def _check_agile_stakeholder_mutation(self, project=False):
        projects = self.mapped("project_id") if self else project
        if not self.env.su and projects and any(
            not agile_project.with_user(self.env.user).has_access("read")
            for agile_project in projects
        ):
            raise AccessError(
                _("You must retain native Odoo Project access to change Agile issues here.")
            )
        roles = {agile_project._agile_role_for_user(self.env.user) for agile_project in projects} if projects else set()
        if roles and not roles <= {"manager", "contributor", "reviewer"}:
            if "stakeholder" in roles:
                raise AccessError(
                    _("Stakeholders can follow this project but cannot change its issues. Ask a project manager for a contributor role.")
                )
            raise AccessError(
                _("Only members of this Agile project can change its issues.")
            )

    def _check_agile_manager_mutation(self):
        projects = self.filtered("agile_issue").mapped("project_id")
        if not self.env.su and projects and any(
            not project.with_user(self.env.user).has_access("read")
            for project in projects
        ):
            raise AccessError(
                _("You must retain native Odoo Project access to manage Agile issues here.")
            )
        if any(
            project._agile_role_for_user(self.env.user) != "manager"
            for project in projects
        ):
            raise AccessError(
                _("Only this project's Agile Manager can archive or delete issues.")
            )

    def _check_agile_transition(self, target_status, target_stage=None):
        """Raise unless the current user's role may move this issue to the target.

        The project's workflow decides. A project without one keeps the built-in rules below.
        """
        self.ensure_one()
        source_status = self.agile_status
        if target_stage and self._agile_workflow():
            if target_stage == self.stage_id:
                return
            if target_stage in self._agile_allowed_transitions().to_status_id.stage_id:
                return
            raise UserError(
                _(
                    "You cannot move this issue from %(source)s to %(target)s. "
                    "Use the next available workflow action or ask a project manager.",
                    source=self.stage_id.name,
                    target=target_stage.name,
                )
            )
        if source_status == target_status:
            return
        role = self._agile_role()
        allowed_edges = self.project_id._agile_edges(role)
        if (source_status, target_status) not in allowed_edges:
            raise UserError(
                _(
                    "You cannot move this issue from %(source)s to %(target)s. "
                    "Use the next available workflow action or ask a project manager.",
                    source=self.stage_id.name,
                    target=self.env["project.task.type"]._agile_main_stage(
                        self.project_id, target_status, include_archived=False
                    ).name or target_status,
                )
            )

    def _check_agile_transition_required_fields(self, target_status, source_stage=None, target_stage=None):
        self.ensure_one()
        if source_stage and target_stage and self._agile_workflow():
            transition = self._agile_workflow().sudo().transition_ids.filtered(
                lambda t: t.from_status_id.stage_id == source_stage and t.to_status_id.stage_id == target_stage
            )[:1]
            if transition:
                text = transition.missing_text(self)
                extra = transition.condition_reasons(self)
                if extra:
                    raise UserError(
                        _(
                            "Before moving this issue to %(stage)s: %(reasons)s.",
                            stage=target_stage.name,
                            reasons=transition.unmet_text(self),
                        )
                    )
                if text:
                    raise UserError(
                        _(
                            "Before moving this issue to %(stage)s, add %(fields)s.",
                            stage=self.stage_id.name,
                            fields=text,
                        )
                    )
                return
        missing = []
        if target_status in ("progress", "review", "done") and not self.user_ids:
            missing.append(_("an assignee"))
        if target_status in ("review", "done") and is_html_empty(self.description):
            missing.append(_("a description"))
        if missing:
            raise UserError(
                _(
                    "Before moving this issue to %(stage)s, add %(fields)s.",
                    stage=self.stage_id.name,
                    fields=_(" and ").join(missing),
                )
            )

    def _agile_transition(self, target_status, allow_cancel_action=False):
        for task in self:
            # The workflow picks the stage when it has a move to this status from here.
            via_workflow = task._agile_workflow().sudo().transition_ids.filtered(
                lambda t: t.from_status_id.stage_id == task.stage_id
                and t.to_status_id.category == target_status
            )[:1].to_status_id.stage_id
            target_stage = via_workflow or self.env["project.task.type"]._agile_main_stage(
                task.project_id, target_status
            )
            if not target_stage:
                raise UserError(
                    _("The target Agile workflow stage is not configured.")
                )
            if not target_stage.active:
                raise UserError(
                    _(
                        "The %(stage)s stage is archived. Ask a project "
                        "manager to restore it before continuing.",
                        stage=target_stage.name,
                    )
                )
            task._write_agile_values(
                {"stage_id": target_stage.id},
                allow_cancel_action=allow_cancel_action,
            )
        return True

    def action_agile_mark_ready(self):
        return self._agile_transition("ready")

    def action_agile_start(self):
        return self._agile_transition("progress")

    def action_agile_send_review(self):
        return self._agile_transition("review")

    def action_agile_return(self):
        return self._agile_transition("progress")

    def action_agile_complete(self):
        return self._agile_transition("done")

    def action_agile_reopen(self):
        self.ensure_one()
        target_status = "backlog" if self.agile_status == "canceled" else "progress"
        return self._agile_transition(target_status)

    def action_agile_cancel(self):
        return self._agile_transition("canceled", allow_cancel_action=True)

    def _allocate_key(self, project):
        """Allocate a unique issue key for the given Agile-enabled project.

        Uses Odoo's ir.sequence with no_gap implementation, which acquires
        a database-level sequence lock — safe for concurrent calls.
        """
        project.ensure_one()
        if not project.agile_key:
            raise ValidationError(
                _("Project '%s' does not have an Agile key configured.") % project.name
            )
        project._ensure_agile_issue_sequence()
        seq_code = f"agile_community.issue_{project.id}"
        seq = self.env["ir.sequence"].sudo()
        issue_sequence = seq.search([("code", "=", seq_code)], limit=1)
        number = issue_sequence.next_by_id()
        if not number:
            raise ValidationError(
                _("Could not allocate an issue key. Contact an administrator.")
            )
        return number
