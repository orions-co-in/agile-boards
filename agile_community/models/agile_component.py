from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError


class AgileProjectComponent(models.Model):
    _name = "agile.project.component"
    _description = "Agile Project Component"
    _order = "sequence, name, id"
    _rec_name = "name"

    name = fields.Char(required=True, index=True)
    project_id = fields.Many2one(
        "project.project", required=True, index=True, ondelete="restrict"
    )
    owner_id = fields.Many2one(
        "res.users",
        string="Default assignee",
        ondelete="set null",
        domain="[('share', '=', False)]",
        help="Assigned to an issue that gets this component when it has no assignee yet. An assignee already set is never changed.",
    )
    description = fields.Text()
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    task_ids = fields.One2many(
        "project.task", "agile_component_id", string="Issues"
    )
    issue_count = fields.Integer(compute="_compute_issue_count")
    can_manage_component = fields.Boolean(compute="_compute_can_manage_component")
    member_user_ids = fields.Many2many(
        "res.users", compute="_compute_member_user_ids", string="Team members"
    )

    _component_name_project_unique = models.Constraint(
        "unique (project_id, name)", "Component names must be unique per project."
    )

    @api.depends("project_id.agile_member_ids.user_id")
    def _compute_member_user_ids(self):
        # The form domain cannot walk project_id on an unsaved record, so it filters on this list.
        for component in self:
            component.member_user_ids = component.project_id.agile_member_ids.user_id

    @api.depends_context("uid")
    @api.depends(
        "project_id.agile_member_ids.user_id",
        "project_id.agile_member_ids.role",
    )
    def _compute_can_manage_component(self):
        is_administrator = self.env.user.has_group("base.group_system")
        for component in self:
            component.can_manage_component = bool(
                is_administrator
                or component.project_id._agile_role_for_user(self.env.user)
                == "manager"
            )

    @api.depends("task_ids", "task_ids.agile_issue")
    def _compute_issue_count(self):
        # Unsaved (onchange) records have NewIds; count by their saved id.
        counts = {component._origin.id: 0 for component in self}
        groups = self.env["project.task"]._read_group(
            [
                ("agile_component_id", "in", [cid for cid in counts if cid]),
                ("agile_issue", "=", True),
            ],
            ["agile_component_id"],
            ["__count"],
        )
        for component, count in groups:
            counts[component.id] = count
        for component in self:
            component.issue_count = counts[component._origin.id]

    def _check_managers(self, projects=None):
        projects = projects or self.mapped("project_id")
        if any(not project.agile_enabled for project in projects):
            raise AccessError(
                _("Components can be configured only on Agile-enabled projects.")
            )
        if any(
            not project.with_user(self.env.user).has_access("read")
            for project in projects
        ):
            raise AccessError(
                _("You must be able to open the Odoo Project to manage its components.")
            )
        if not self.env.user.has_group("base.group_system") and any(
            project._agile_role_for_user(self.env.user) != "manager"
            for project in projects
        ):
            raise AccessError(
                _("Only this Agile project's Manager can configure components.")
            )

    @api.model_create_multi
    def create(self, vals_list):
        project_ids = [
            vals.get("project_id") or self.env.context.get("default_project_id")
            for vals in vals_list
        ]
        projects = self.env["project.project"].browse(
            [project_id for project_id in project_ids if project_id]
        ).exists()
        self._check_managers(projects)
        for vals in vals_list:
            project_id = (
                vals.get("project_id")
                or self.env.context.get("default_project_id")
            )
            if vals.get("owner_id") and self.env["project.project"].browse(
                project_id
            )._agile_role_for_user(
                self.env["res.users"].browse(vals["owner_id"])
            ) == "none":
                raise ValidationError(
                    _("The component owner must be a member of this Agile project.")
                )
        return super().create(vals_list)

    def write(self, vals):
        projects = self.mapped("project_id")
        target = (
            self.env["project.project"].browse(vals["project_id"])
            if vals.get("project_id")
            else projects
        )
        self._check_managers(projects | target)
        if "project_id" in vals:
            moving = self.filtered(
                lambda component: component.project_id.id != vals["project_id"]
            )
            referenced = self.env["project.task"].sudo().with_context(
                active_test=False
            ).search_count([("agile_component_id", "in", moving.ids)])
            if referenced:
                raise UserError(
                    _(
                        "A component assigned to issues cannot be moved to another project. "
                        "Create a new component in the destination project instead."
                    )
                )
        if self.filtered(lambda component: not component.active) and any(
            key in vals
            for key in ("name", "project_id", "owner_id", "description", "sequence")
        ):
            raise UserError(
                _("Archived components are read-only; reactivate one to edit it.")
            )
        for component in self:
            project = target if "project_id" in vals else component.project_id
            owner_id = vals.get("owner_id", component.owner_id.id)
            if owner_id and project._agile_role_for_user(
                self.env["res.users"].browse(owner_id)
            ) == "none":
                raise ValidationError(
                    _("The component owner must be a member of this Agile project.")
                )
        return super().write(vals)

    def unlink(self):
        self._check_managers()
        referenced = self.env["project.task"].with_context(
            active_test=False
        ).search_count([("agile_component_id", "in", self.ids)])
        if referenced:
            raise UserError(
                _("A component used by issues cannot be deleted. Archive it instead.")
            )
        return super().unlink()


class ProjectProject(models.Model):
    _inherit = "project.project"

    agile_component_ids = fields.One2many(
        "agile.project.component", "project_id", string="Components"
    )

    def action_manage_agile_components(self):
        self.ensure_one()
        self.check_access("read")
        if not self.agile_enabled:
            raise AccessError(_("Components are available only on Agile-enabled projects."))
        if (
            not self.env.user.has_group("base.group_system")
            and self._agile_role_for_user(self.env.user) != "manager"
        ):
            raise AccessError(
                _("Only this Agile project's Manager can configure components.")
            )
        return {
            "type": "ir.actions.act_window",
            "name": _("Components"),
            "res_model": "agile.project.component",
            "view_mode": "list,form",
            "domain": [("project_id", "=", self.id)],
            "context": {"default_project_id": self.id},
        }
