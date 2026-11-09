from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


class AgileProjectQuickFilter(models.Model):
    _name = "agile.project.quick.filter"
    _description = "Agile Project Quick Filter"
    _order = "sequence, name, id"

    name = fields.Char(required=True)
    project_id = fields.Many2one(
        "project.project", required=True, ondelete="cascade", index=True
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    member_user_ids = fields.Many2many(
        "res.users", compute="_compute_member_user_ids", string="Team members"
    )
    filter_type = fields.Selection(
        [
            ("assignee", "Assignee"),
            ("unassigned", "Unassigned"),
            ("priority", "Priority"),
            ("issue_type", "Issue Type"),
            ("component", "Component"),
        ],
        required=True,
    )
    user_id = fields.Many2one(
        "res.users", string="Assignee", ondelete="restrict"
    )

    @api.depends("project_id.agile_member_ids.user_id")
    def _compute_member_user_ids(self):
        # The form domain cannot walk project_id on an unsaved record, so it filters on this list.
        for quick_filter in self:
            quick_filter.member_user_ids = quick_filter.project_id.agile_member_ids.user_id
    priority = fields.Selection(
        [
            ("0", "Low priority"), ("1", "Medium priority"),
            ("2", "High priority"), ("3", "Urgent"),
        ]
    )
    issue_type_id = fields.Many2one(
        "agile_community.task_type", string="Issue Type", ondelete="restrict"
    )
    component_id = fields.Many2one(
        "agile.project.component", string="Component", ondelete="restrict"
    )

    _quick_filter_project_name_unique = models.Constraint(
        "unique (project_id, name)",
        "Quick filter names must be unique per project.",
    )

    def _check_managers(self, projects=None):
        projects = projects or self.mapped("project_id")
        if any(not project.agile_enabled for project in projects):
            raise AccessError(
                _("Quick filters can be configured only on Agile-enabled projects.")
            )
        if any(
            not project.with_user(self.env.user).has_access("read")
            for project in projects
        ):
            raise AccessError(
                _("You must be able to open the Odoo Project to manage its quick filters.")
            )
        if not self.env.user.has_group("base.group_system") and any(
            project._agile_role_for_user(self.env.user) != "manager"
            for project in projects
        ):
            raise AccessError(
                _("Only this Agile project's Manager can configure shared quick filters.")
            )

    def _filter_value_id(self, field_name):
        """Return the stored value of a filter field, whether a record or a plain value."""
        self.ensure_one()
        value = self[field_name]
        return value.id if hasattr(value, "id") else value

    def _check_values(self, vals, project):
        filter_type = vals.get("filter_type", self.filter_type if self else False)
        required_field = {
            "assignee": "user_id",
            "priority": "priority",
            "issue_type": "issue_type_id",
            "component": "component_id",
        }.get(filter_type)
        if required_field and not vals.get(
            required_field,
            self._filter_value_id(required_field) if self else False,
        ):
            raise ValidationError(
                _("Choose a value for this quick filter before saving it.")
            )
        for field_name, expected_model in (
            ("issue_type_id", "agile_community.task_type"),
            ("component_id", "agile.project.component"),
        ):
            value_id = vals.get(
                field_name,
                self[field_name].id if self else False,
            )
            if value_id:
                value = self.env[expected_model].browse(value_id).exists()
                if not value or (
                    field_name == "component_id"
                    and value.project_id != project
                ) or (
                    field_name == "issue_type_id"
                    and value.project_ids
                    and project not in value.project_ids
                ) or not value.active:
                    raise ValidationError(
                        _("Quick filter values must be active and available to this project.")
                    )
        if filter_type == "assignee":
            user_id = vals.get("user_id", self.user_id.id if self else False)
            user = self.env["res.users"].browse(user_id).exists()
            if (
                not user
                or not user.active
                or user.share
                or project._agile_role_for_user(user) == "none"
            ):
                raise ValidationError(
                    _("The quick filter assignee must be an active internal member of this project.")
                )

    @api.model_create_multi
    def create(self, vals_list):
        project_ids = []
        for vals in vals_list:
            project_id = vals.get("project_id") or self.env.context.get(
                "default_project_id"
            )
            project = self.env["project.project"].browse(project_id).exists()
            if not project:
                raise ValidationError(
                    _("Choose an Agile project before creating a shared quick filter.")
                )
            vals["project_id"] = project.id
            project_ids.append(project.id)
        projects = self.env["project.project"].browse(project_ids).exists()
        self._check_managers(projects)
        for vals in vals_list:
            project = self.env["project.project"].browse(vals.get("project_id"))
            self._check_values(vals, project)
        return super().create(vals_list)

    def write(self, vals):
        projects = self.mapped("project_id")
        target = (
            self.env["project.project"].browse(vals["project_id"])
            if vals.get("project_id")
            else projects
        )
        self._check_managers(projects | target)
        # Archiving or reordering must not re-validate the filter's content.
        if set(vals) - {"active", "sequence"}:
            for record in self:
                project = target if "project_id" in vals else record.project_id
                record._check_values(vals, project)
        return super().write(vals)

    def unlink(self):
        self._check_managers()
        return super().unlink()

    def action_open_issues(self):
        self.ensure_one()
        self.check_access("read")
        project = self.project_id
        if (
            not project.agile_enabled
            or project._agile_role_for_user(self.env.user) == "none"
        ):
            raise AccessError(_("You are not a member of this Agile project."))
        if not self.active:
            raise AccessError(_("This shared quick filter is archived."))
        action = project.action_view_tasks()
        condition = {
            "assignee": [("user_ids", "in", [self.user_id.id])],
            "unassigned": [("user_ids", "=", False)],
            "priority": [("priority", "=", self.priority)],
            "issue_type": [("agile_task_type_id", "=", self.issue_type_id.id)],
            "component": [("agile_component_id", "=", self.component_id.id)],
        }[self.filter_type]
        action["domain"] = list(action.get("domain") or []) + condition
        action["name"] = self.name
        return action


class ProjectProject(models.Model):
    _inherit = "project.project"

    agile_quick_filter_ids = fields.One2many(
        "agile.project.quick.filter", "project_id", string="Quick Filters"
    )

    def action_manage_agile_quick_filters(self):
        self.ensure_one()
        self.check_access("read")
        if not self.agile_enabled:
            raise AccessError(
                _("Quick filters are available only on Agile-enabled projects.")
            )
        if (
            not self.env.user.has_group("base.group_system")
            and self._agile_role_for_user(self.env.user) != "manager"
        ):
            raise AccessError(
                _("Only this Agile project's Manager can configure shared quick filters.")
            )
        return {
            "type": "ir.actions.act_window",
            "name": _("Shared Quick Filters"),
            "res_model": "agile.project.quick.filter",
            "view_mode": "list,form",
            "domain": [("project_id", "=", self.id)],
            "context": {"default_project_id": self.id},
        }
