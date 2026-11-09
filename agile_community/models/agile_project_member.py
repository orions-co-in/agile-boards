from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


class AgileProjectMember(models.Model):
    _name = "agile.project.member"
    _description = "Agile Project Team Member"
    _order = "project_id, role, user_id"

    project_id = fields.Many2one(
        "project.project",
        string="Project",
        required=True,
        index=True,
        ondelete="cascade",
    )
    user_id = fields.Many2one(
        "res.users",
        string="Team member",
        required=True,
        index=True,
        ondelete="restrict",
        domain=[("share", "=", False)],
        help=(
            "Select an active internal user who can already open this project through "
            "native Odoo Project rules. This Agile role does not grant project access."
        ),
    )
    role = fields.Selection(
        [
            ("manager", "Project Manager"),
            ("contributor", "Contributor"),
            ("reviewer", "Reviewer"),
            ("stakeholder", "Stakeholder"),
        ],
        required=True,
        default="contributor",
    )
    assigned_by_id = fields.Many2one(
        "res.users",
        string="Added by",
        required=True,
        default=lambda self: self.env.user,
        readonly=True,
    )

    _project_user_unique = models.Constraint(
        "unique (project_id, user_id)",
        "A user can have only one Agile role in a project.",
    )

    @api.constrains("project_id", "user_id", "role")
    def _check_member_scope(self):
        for member in self:
            if not member.project_id.agile_enabled:
                raise ValidationError(
                    _("Agile team roles can only be assigned to an Agile project.")
                )
            if member.user_id.share:
                raise ValidationError(
                    _("Portal users cannot be assigned an Agile team role.")
                )
            if not member.user_id.active:
                raise ValidationError(
                    _("Archive or reactivate an internal user before changing Agile team access.")
                )
            if not member.user_id.has_group("project.group_project_user"):
                raise ValidationError(
                    _("The team member must already have native Odoo Project access.")
                )
            if not member.project_id.with_user(member.user_id).has_access("read"):
                raise ValidationError(
                    _(
                        "The team member must already be able to open this project in Odoo Project. "
                        "Project-level access is required; access to an individual task is not enough."
                    )
                )
            if (
                member.project_id.company_id
                and member.project_id.company_id not in member.user_id.company_ids
            ):
                raise ValidationError(
                    _("The team member must have access to the project's company.")
                )

    def _is_trusted_role_seed(self):
        """Do not let an RPC-controlled context flag bypass manager checks."""
        return self.env.su and self.env.context.get("agile_role_seed")

    @api.model_create_multi
    def create(self, vals_list):
        trusted_seed = self._is_trusted_role_seed()
        vals_list = [dict(vals) for vals in vals_list]
        if not trusted_seed:
            # The audit actor is server-authored; readonly view attributes alone
            # are not a protection against callers supplying this field over RPC.
            for vals in vals_list:
                vals["assigned_by_id"] = self.env.uid
            for vals in vals_list:
                project = self.env["project.project"].browse(vals.get("project_id"))
                self._check_project_manager(project)
        members = super().create(vals_list)
        if not trusted_seed:
            for member in members:
                member.project_id._agile_post_audit_note(
                    _(
                        "%(user)s was added to the Agile team as %(role)s.",
                        user=member.user_id.display_name,
                        role=member._fields["role"].convert_to_export(member.role, member),
                    )
                )
        return members

    def write(self, vals):
        if not self._is_trusted_role_seed():
            if {"project_id", "user_id", "assigned_by_id"} & vals.keys():
                raise ValidationError(
                    _("Edit a team member's role or remove and re-add the member; identity and project cannot be changed.")
                )
            for project in self.mapped("project_id"):
                self._check_project_manager(project)
                if "role" in vals and vals["role"] != "manager" and self.filtered(
                    lambda member: member.project_id == project
                    and member.role == "manager"
                ) and not self.search_count([
                    ("project_id", "=", project.id),
                    ("role", "=", "manager"),
                    ("id", "not in", self.ids),
                ]):
                    raise ValidationError(
                        _("Keep at least one Agile Manager assigned to each project.")
                    )
        changed_roles = {
            member.id: (member.role, member.user_id, member.project_id)
            for member in self
            if "role" in vals and vals["role"] != member.role
        }
        result = super().write(vals)
        if not self._is_trusted_role_seed():
            for member in self.browse(changed_roles):
                old_role, old_user, old_project = changed_roles[member.id]
                old_project._agile_post_audit_note(
                    _(
                        "Agile team role for %(user)s changed from %(old)s to %(new)s.",
                        user=old_user.display_name,
                        old=old_role,
                        new=member.role,
                    )
                )
        return result

    def unlink(self):
        if not self._is_trusted_role_seed():
            for project in self.mapped("project_id"):
                self._check_project_manager(project)
                if self.filtered(
                    lambda member: member.project_id == project
                    and member.role == "manager"
                ) and not self.search_count([
                    ("project_id", "=", project.id),
                    ("role", "=", "manager"),
                    ("id", "not in", self.ids),
                ]):
                    raise ValidationError(
                        _("Keep at least one Agile Manager assigned to each project.")
                    )
        if not self._is_trusted_role_seed():
            for member in self:
                member.project_id._agile_post_audit_note(
                    _(
                        "%(user)s was removed from the Agile team (role: %(role)s).",
                        user=member.user_id.display_name,
                        role=member.role,
                    )
                )
        return super().unlink()

    def _check_project_manager(self, project):
        if not project or not project.agile_enabled:
            raise AccessError(
                _("Only this project's Agile Manager can manage its team roles.")
            )
        if not project.with_user(self.env.user).has_access("read"):
            raise AccessError(
                _("You must retain native Odoo Project access to manage this Agile team.")
            )
        if project._agile_role_for_user(self.env.user) != "manager":
            raise AccessError(
                _("Only this project's Agile Manager can manage its team roles.")
            )

    @api.model
    def _readable_project_ids_for_roles(self, roles):
        members = self.sudo().search([
            ("user_id", "=", self.env.uid),
            ("role", "in", roles),
        ])
        projects = members.mapped("project_id")
        Project = self.env["project.project"]
        if "manager" in roles and Project._agile_user_is_odoo_admin(self.env.user):
            # The implicit manager role covers every Agile project, not only team rows.
            projects |= Project.sudo().search([("agile_enabled", "=", True)])
        return projects.filtered(
            lambda project: project.with_user(self.env.user).has_access("read")
        ).ids
