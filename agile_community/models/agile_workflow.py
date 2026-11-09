from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import is_html_empty

# (name, from, to, contributor, reviewer, manager): today's rules as data (W-201).
DEFAULT_TRANSITIONS = [
    ("Plan into sprint", "backlog", "ready", True, False, True),
    ("Back to backlog", "ready", "backlog", False, False, True),
    ("Start", "ready", "progress", True, False, True),
    ("Send to review", "progress", "review", True, False, True),
    ("Return", "review", "progress", False, True, True),
    ("Complete", "review", "done", False, True, True),
    ("Reopen", "done", "progress", False, False, True),
    ("Reopen", "canceled", "backlog", False, False, True),
    ("Cancel", "backlog", "canceled", False, False, True),
    ("Cancel", "ready", "canceled", False, False, True),
    ("Cancel", "progress", "canceled", False, False, True),
    ("Cancel", "review", "canceled", False, False, True),
]
DEFAULT_STATUS_ORDER = ["backlog", "ready", "progress", "review", "done", "canceled"]
# Issue fields a transition may require (records of agile.workflow.field carry the wording).
REQUIRED_FIELD_CODES = ["user_ids", "description", "story_points", "date_deadline", "parent_id", "sprint_id"]
# Required fields of each default transition, matching today's hard-coded rules.
DEFAULT_REQUIRED = {
    ("ready", "progress"): ["user_ids"],
    ("progress", "review"): ["user_ids", "description"],
    ("review", "progress"): ["user_ids"],
    ("review", "done"): ["user_ids", "description"],
    ("done", "progress"): ["user_ids"],
}
ROLE_FLAGS = {
    "contributor": "allow_contributor",
    "reviewer": "allow_reviewer",
    "manager": "allow_manager",
}


class AgileWorkflowField(models.Model):
    _name = "agile.workflow.field"
    _description = "Issue field a workflow transition can require"
    _order = "sequence, id"

    code = fields.Selection([(code, code) for code in REQUIRED_FIELD_CODES], required=True)
    name = fields.Char(required=True, translate=True, help="Shown in the workflow editor, for example Assignee.")
    phrase = fields.Char(required=True, translate=True, help="Reads after 'add', for example an assignee.")
    sequence = fields.Integer(default=10)

    _code_unique = models.Constraint("unique (code)", "Each issue field is listed once.")


class AgileWorkflowMixin(models.AbstractModel):
    _name = "agile.workflow.mixin"
    _description = "Agile workflow configuration access"

    def _check_workflow_managers(self, projects):
        if self.env.su:
            return
        if any(not project.with_user(self.env.user).has_access("read") for project in projects):
            raise AccessError(_("You must be able to open the Odoo Project to manage its workflows."))
        if any(
            not project.agile_enabled or project._agile_role_for_user(self.env.user) != "manager"
            for project in projects
        ):
            raise AccessError(_("Only this project's Agile Manager can change its workflows."))


class AgileWorkflow(models.Model):
    _name = "agile.workflow"
    _inherit = ["agile.workflow.mixin"]
    _description = "Agile Workflow"
    _order = "project_id, is_default desc, name"

    name = fields.Char(required=True)
    project_id = fields.Many2one("project.project", required=True, index=True, ondelete="cascade")
    is_default = fields.Boolean(
        string="Default",
        help="Used by every issue type that has no workflow of its own.",
    )
    task_type_ids = fields.Many2many(
        "agile_community.task_type",
        "agile_workflow_task_type_rel",
        "workflow_id",
        "task_type_id",
        string="Issue types",
    )
    status_ids = fields.One2many("agile.workflow.status", "workflow_id", string="Statuses")
    transition_ids = fields.One2many("agile.workflow.transition", "workflow_id", string="Transitions")

    @api.constrains("project_id", "is_default")
    def _check_one_default(self):
        for workflow in self.filtered("is_default"):
            if self.search_count([
                ("project_id", "=", workflow.project_id.id),
                ("is_default", "=", True),
                ("id", "!=", workflow.id),
            ]):
                raise ValidationError(_("A project has one default workflow."))

    @api.constrains("project_id", "task_type_ids")
    def _check_type_used_once(self):
        for workflow in self:
            for task_type in workflow.task_type_ids:
                if self.search_count([
                    ("project_id", "=", workflow.project_id.id),
                    ("task_type_ids", "in", task_type.id),
                    ("id", "!=", workflow.id),
                ]):
                    raise ValidationError(
                        _("%(type)s already has a workflow in this project.", type=task_type.name)
                    )

    @api.constrains("project_id")
    def _check_agile_project(self):
        if any(not workflow.project_id.agile_enabled for workflow in self):
            raise ValidationError(_("Workflows can only be set on an Agile project."))

    @api.model_create_multi
    def create(self, vals_list):
        projects = self.env["project.project"].browse([v.get("project_id") for v in vals_list]).exists()
        self._check_workflow_managers(projects)
        return super().create(vals_list)

    def write(self, vals):
        if "project_id" in vals:
            raise ValidationError(_("A workflow cannot be moved to another project."))
        self._check_workflow_managers(self.project_id)
        return super().write(vals)

    def unlink(self):
        self._check_workflow_managers(self.project_id)
        if self.filtered("is_default"):
            raise ValidationError(_("The default workflow cannot be deleted."))
        return super().unlink()

    def allowed_transitions(self, from_stage, role):
        """Transitions out of a stage that this Agile role may take."""
        self.ensure_one()
        flag = ROLE_FLAGS.get(role)
        if not flag:
            return self.env["agile.workflow.transition"]
        return self.transition_ids.filtered(
            lambda transition: transition.from_status_id.stage_id == from_stage and transition[flag]
        )


class AgileWorkflowStatus(models.Model):
    _name = "agile.workflow.status"
    _inherit = ["agile.workflow.mixin"]
    _description = "Agile Workflow Status"
    _order = "workflow_id, sequence, id"

    workflow_id = fields.Many2one("agile.workflow", required=True, index=True, ondelete="cascade")
    stage_id = fields.Many2one(
        "project.task.type",
        string="Stage",
        required=True,
        ondelete="restrict",
        domain="[('project_ids', 'in', parent.project_id)]",
    )
    sequence = fields.Integer(default=10)
    name = fields.Char(related="stage_id.name", readonly=False)
    category = fields.Selection(related="stage_id.agile_status", string="Category")

    _workflow_stage_unique = models.Constraint(
        "unique (workflow_id, stage_id)", "A status appears once in a workflow."
    )

    @api.constrains("workflow_id", "stage_id")
    def _check_stage_in_project(self):
        for status in self:
            if status.workflow_id.project_id not in status.stage_id.project_ids:
                raise ValidationError(_("Choose a stage of this workflow's project."))

    @api.model_create_multi
    def create(self, vals_list):
        workflows = self.env["agile.workflow"].browse([v.get("workflow_id") for v in vals_list]).exists()
        self._check_workflow_managers(workflows.project_id)
        return super().create(vals_list)

    def write(self, vals):
        if "workflow_id" in vals:
            raise ValidationError(_("A status cannot move to another workflow."))
        self._check_workflow_managers(self.workflow_id.project_id)
        return super().write(vals)

    def unlink(self):
        self._check_workflow_managers(self.workflow_id.project_id)
        return super().unlink()


class AgileWorkflowTransition(models.Model):
    _name = "agile.workflow.transition"
    _inherit = ["agile.workflow.mixin"]
    _description = "Agile Workflow Transition"
    _order = "workflow_id, from_status_id, to_status_id"

    name = fields.Char(required=True, help="The button label, for example Start.")
    workflow_id = fields.Many2one("agile.workflow", required=True, index=True, ondelete="cascade")
    from_status_id = fields.Many2one(
        "agile.workflow.status",
        string="From",
        required=True,
        ondelete="cascade",
        domain="[('workflow_id', '=', parent.id)]",
    )
    to_status_id = fields.Many2one(
        "agile.workflow.status",
        string="To",
        required=True,
        ondelete="cascade",
        domain="[('workflow_id', '=', parent.id)]",
    )
    allow_contributor = fields.Boolean(string="Contributors")
    allow_reviewer = fields.Boolean(string="Reviewers")
    allow_manager = fields.Boolean(string="Managers", default=True)
    required_field_ids = fields.Many2many(
        "agile.workflow.field",
        "agile_workflow_transition_field_rel",
        "transition_id",
        "field_id",
        string="Required issue fields",
        help="The issue must have these filled in before it can take this transition.",
    )

    require_no_open_subtasks = fields.Boolean(
        string="No open sub-issues",
        help="Every sub-issue of the issue must be Done or Canceled before it can take this transition.",
    )
    require_not_blocked = fields.Boolean(
        string="Not blocked",
        help="The issue must have no manual blocker and no open dependency before it can take this transition.",
    )

    _edge_unique = models.Constraint(
        "unique (workflow_id, from_status_id, to_status_id)",
        "Each status pair has one transition.",
    )

    @api.constrains("workflow_id", "from_status_id", "to_status_id")
    def _check_edge(self):
        for transition in self:
            ends = transition.from_status_id | transition.to_status_id
            if ends.workflow_id != transition.workflow_id:
                raise ValidationError(_("A transition connects two statuses of its own workflow."))
            if transition.from_status_id == transition.to_status_id:
                raise ValidationError(_("A transition needs two different statuses."))

    def missing_fields(self, task):
        """Names of the required issue fields that this issue still has empty."""
        self.ensure_one()
        missing = []
        for name in self.required_field_ids.mapped("code"):
            if name == "description":
                empty = is_html_empty(task.description)
            elif name == "story_points":
                empty = not task.story_points_estimated
            else:
                empty = not task[name]
            if empty:
                missing.append(name)
        return missing

    def missing_custom_fields(self, task):
        """Project fields the issue still lacks for this move; agile_pro defines them."""
        return []

    def _agile_extra_need_names(self):
        """Names of the further things this move requires (project fields, with agile_pro)."""
        return []

    def _agile_extra_need_ids(self):
        return set()

    def _agile_copy_values(self):
        """Values a copy of this move takes from agile_pro (approvers, required project fields)."""
        return {}

    def _agile_template_extras(self):
        """What agile_pro adds when this move is written to a template."""
        return {}

    def condition_reasons(self, task):
        """What the move's conditions (beyond filled fields) still need, as short phrases."""
        self.ensure_one()
        reasons = []
        if self.require_no_open_subtasks:
            open_children = task.child_ids.filtered(
                lambda child: child.agile_issue and child.agile_status not in ("done", "canceled")
            )
            if open_children:
                reasons.append(
                    _("finish its 1 open sub-issue") if len(open_children) == 1
                    else _("finish its %s open sub-issues", len(open_children))
                )
        if self.require_not_blocked and task.agile_is_blocked:
            reasons.append(_("clear the blocker"))
        return reasons

    def unmet_text(self, task):
        """Everything that stops the issue taking this move now, in words ('' when nothing does)."""
        self.ensure_one()
        reasons = []
        fields_text = self.missing_text(task)
        if fields_text:
            reasons.append(_("add %s", fields_text))
        return "; ".join(reasons + self.condition_reasons(task))

    def missing_text(self, task):
        """'an assignee and a description', or an empty string when nothing is missing."""
        missing = self.missing_fields(task)
        phrases = self.required_field_ids.filtered(lambda field: field.code in missing).mapped("phrase")
        phrases += [_("a value for %s", field.name) for field in self.missing_custom_fields(task)]
        return _(" and ").join(phrases)

    @api.model_create_multi
    def create(self, vals_list):
        workflows = self.env["agile.workflow"].browse([v.get("workflow_id") for v in vals_list]).exists()
        self._check_workflow_managers(workflows.project_id)
        return super().create(vals_list)

    def write(self, vals):
        if "workflow_id" in vals:
            raise ValidationError(_("A transition cannot move to another workflow."))
        self._check_workflow_managers(self.workflow_id.project_id)
        return super().write(vals)

    def unlink(self):
        self._check_workflow_managers(self.workflow_id.project_id)
        return super().unlink()


class ProjectProject(models.Model):
    _inherit = "project.project"

    agile_workflow_ids = fields.One2many("agile.workflow", "project_id", string="Workflows")

    def _ensure_agile_default_workflow(self):
        """Create the default workflow (today's six statuses and rules) where it is missing."""
        # Seeding a new project is not a change worth a history line (NU-44).
        quiet = self.with_context(agile_workflow_quiet=True).env
        workflow_model = quiet["agile.workflow"].sudo()
        field_model = self.env["agile.workflow.field"].sudo()
        stage_model = self.env["project.task.type"].sudo().with_context(active_test=False)
        for project in self.filtered("agile_enabled"):
            if workflow_model.search_count([("project_id", "=", project.id), ("is_default", "=", True)]):
                continue
            stages = {
                stage.agile_status: stage
                for stage in stage_model.search([
                    ("project_ids", "=", project.id), ("agile_status", "!=", False),
                ])
            }
            if set(stages) != set(DEFAULT_STATUS_ORDER):
                continue  # Stages are seeded first; try again when they exist.
            workflow = workflow_model.create({
                "name": _("Default workflow"),
                "project_id": project.id,
                "is_default": True,
                "status_ids": [
                    (0, 0, {"stage_id": stages[key].id, "sequence": (index + 1) * 10})
                    for index, key in enumerate(DEFAULT_STATUS_ORDER)
                ],
            })
            by_category = {status.category: status for status in workflow.status_ids}
            quiet["agile.workflow.transition"].sudo().create([
                {
                    "name": name,
                    "workflow_id": workflow.id,
                    "from_status_id": by_category[source].id,
                    "to_status_id": by_category[target].id,
                    "allow_contributor": contributor,
                    "allow_reviewer": reviewer,
                    "allow_manager": manager,
                    "required_field_ids": [
                        (6, 0, field_model.search([
                            ("code", "in", DEFAULT_REQUIRED.get((source, target), [])),
                        ]).ids)
                    ],
                }
                for name, source, target, contributor, reviewer, manager in DEFAULT_TRANSITIONS
            ])


    def _agile_backfill_default_required_fields(self):
        """Give the default transitions of existing projects today's required fields (W-202)."""
        field_model = self.env["agile.workflow.field"].sudo()
        for workflow in self.env["agile.workflow"].sudo().search([("is_default", "=", True)]):
            for transition in workflow.transition_ids:
                names = DEFAULT_REQUIRED.get(
                    (transition.from_status_id.category, transition.to_status_id.category), []
                )
                if names and not transition.required_field_ids:
                    transition.required_field_ids = field_model.search([("code", "in", names)])


class ProjectTask(models.Model):
    _inherit = "project.task"

    def _agile_workflow(self):
        """The workflow for this issue's type, else the project's default."""
        self.ensure_one()
        workflows = self.project_id.sudo().agile_workflow_ids
        if self.agile_task_type_id:
            own = workflows.filtered(lambda w: self.agile_task_type_id in w.task_type_ids)
            if own:
                return own[:1]
        return workflows.filtered("is_default")[:1]

    agile_transition_hint = fields.Char(compute="_compute_agile_transition_hint")
    agile_missing_fields = fields.Char(
        compute="_compute_agile_transition_hint",
        help="Comma-separated names of the fields the next moves still need.",
    )

    agile_step_reasons = fields.Json(
        compute="_compute_agile_transition_hint",
        help="What stops each next step, by the category it leads to; the card buttons show it.",
    )

    @api.depends("stage_id", "user_ids", "description", "story_points", "story_points_estimated",
                 "date_deadline", "parent_id", "sprint_id", "agile_task_type_id",
                 "child_ids.stage_id", "child_ids.agile_issue", "agile_is_blocked")
    def _compute_agile_transition_hint(self):
        for task in self:
            hint, names, by_category = "", [], {}
            if task.agile_issue:
                for transition in task._agile_allowed_transitions():
                    text = transition.unmet_text(task)
                    if text and transition.to_status_id.category != "canceled":
                        if transition.condition_reasons(task):
                            line = _("Before %(status)s: %(reasons)s.", status=transition.to_status_id.name, reasons=text)
                        else:
                            line = _("Before %(status)s: add %(fields)s.", status=transition.to_status_id.name,
                                     fields=transition.missing_text(task))
                        hint = f"{hint} {line}".strip()
                        names += [n for n in transition.missing_fields(task) if n not in names]
                        by_category[transition.to_status_id.category] = line
            task.agile_transition_hint = hint
            task.agile_missing_fields = ",".join(names)
            task.agile_step_reasons = by_category

    def agile_allowed_moves(self):
        """The moves the current user may make from the card's stage, for the phone Move-to sheet."""
        self.ensure_one()
        self.check_access("read")
        return [
            {
                "name": transition.name,
                "stage_id": transition.to_status_id.stage_id.id,
                "stage": transition.to_status_id.name,
                "reason": transition.unmet_text(self),
            }
            for transition in self._agile_allowed_transitions()
        ]

    def _agile_allowed_transitions(self, role=None):
        """Transitions out of the current stage that a role (default: the current user's) may take."""
        self.ensure_one()
        role = self._agile_role() if role is None else role
        workflow = self._agile_workflow().sudo()
        base = workflow.allowed_transitions(self.stage_id, role)
        scheme = self.project_id.agile_permission_scheme or "standard"
        if scheme == "standard" or role not in ("contributor", "reviewer"):
            return base
        if scheme == "custom":
            from .agile_permission import EDGES  # local: agile_permission imports this module's neighbours

            # The scheme decides which kinds of move a role may take. A grant the workflow does not already
            # give the role (Standard's) is added from the manager's moves; a withdrawn one is removed.
            edges = self.project_id._agile_edges(role)
            standard = EDGES["standard"].get(role, set())
            manager_moves = workflow.allowed_transitions(self.stage_id, "manager")

            def pair(transition):
                return (transition.from_status_id.category, transition.to_status_id.category)

            return (base | manager_moves.filtered(lambda t: pair(t) in edges - standard)).filtered(
                lambda t: pair(t) in edges
            )
        if scheme == "strict":
            return base.filtered(lambda t: t.to_status_id.category != "done")  # only managers complete
        # Open: contributors and reviewers share each other's moves; contributors may also reopen and cancel.
        extra = workflow.allowed_transitions(self.stage_id, "contributor") | workflow.allowed_transitions(
            self.stage_id, "reviewer"
        )
        if role == "contributor":
            extra |= workflow.allowed_transitions(self.stage_id, "manager").filtered(
                lambda t: t.to_status_id.category == "canceled"
                or t.from_status_id.category in ("done", "canceled")
            )
        return base | extra

    def _agile_workflow_moves(self, role):
        """(from, to) status pairs a role may take now, or None when the project has no workflow."""
        self.ensure_one()
        if not self._agile_workflow():
            return None
        return {
            (t.from_status_id.category, t.to_status_id.category)
            for t in self._agile_allowed_transitions(role)
        }

    def _agile_workflow_transition(self, target_stage):
        """The transition from this issue's stage to a stage, whoever may take it (empty if none)."""
        self.ensure_one()
        return self._agile_workflow().sudo().transition_ids.filtered(
            lambda t: t.from_status_id.stage_id == self.stage_id and t.to_status_id.stage_id == target_stage
        )[:1]
