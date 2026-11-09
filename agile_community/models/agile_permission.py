"""Permission schemes and restricted issues (D-943, C-943).

A scheme says which roles may take which kinds of move. Three are built in and not editable; a project can also
choose Custom (T-1142) and edit the Contributor and Reviewer columns of its own copy, within safe limits: managers
always may, stakeholders never may, and releases and sprints stay with managers.
A restricted issue is hidden by a record rule from everyone except the people named on it,
its assignees, its reporter and the project's managers.
"""
from markupsafe import Markup, escape

from odoo import Command, _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

SCHEMES = [("standard", "Standard"), ("open", "Open"), ("strict", "Strict"), ("custom", "Custom")]
SCHEME_SENTENCES = {
    "standard": "Contributors move issues forward, reviewers return and complete them, managers do the rest. This is how Agile has always worked.",
    "open": "Contributors and reviewers share moves, and contributors can also complete, reopen and cancel issues, change sprint membership and set roadmap dates.",
    "custom": "Your team picks which of the Contributor and Reviewer roles may take each kind of move. Managers always may; stakeholders read only.",
    "strict": "Only managers complete, reopen or cancel issues, change sprint membership and set roadmap dates. Reviewers can return an issue to work but not complete it.",
}
FORWARD = {("backlog", "ready"), ("ready", "progress"), ("progress", "review")}
RETURN = {("review", "progress")}
COMPLETE = {("review", "done")}
LIFECYCLE = {
    ("done", "progress"), ("ready", "backlog"), ("canceled", "backlog"), ("backlog", "canceled"),
    ("ready", "canceled"), ("progress", "canceled"), ("review", "canceled"),
}
EVERYTHING = FORWARD | RETURN | COMPLETE | LIFECYCLE
EDGES = {
    "standard": {"manager": EVERYTHING, "contributor": FORWARD, "reviewer": RETURN | COMPLETE},
    "open": {"manager": EVERYTHING, "contributor": EVERYTHING, "reviewer": FORWARD | RETURN | COMPLETE},
    "strict": {"manager": EVERYTHING, "contributor": FORWARD, "reviewer": RETURN},
}
ACTION_ROLES = {
    "sprint_membership": {"standard": {"manager"}, "open": {"manager", "contributor"}, "strict": {"manager"}},
    "roadmap_dates": {"standard": {"manager"}, "open": {"manager", "contributor"}, "strict": {"manager"}},
}
# One row per kind of action, for the Permissions page: label and who may, per scheme.
MATRIX = [
    ("forward", "Move forward to Review", {"standard": ["manager", "contributor"], "open": ["manager", "contributor", "reviewer"], "strict": ["manager", "contributor"]}),
    ("return", "Return an issue to work", {"standard": ["manager", "reviewer"], "open": ["manager", "contributor", "reviewer"], "strict": ["manager", "reviewer"]}),
    ("complete", "Complete an issue", {"standard": ["manager", "reviewer"], "open": ["manager", "contributor", "reviewer"], "strict": ["manager"]}),
    ("lifecycle", "Reopen or cancel an issue", {"standard": ["manager"], "open": ["manager", "contributor"], "strict": ["manager"]}),
    ("sprint_membership", "Change sprint membership", {"standard": ["manager"], "open": ["manager", "contributor"], "strict": ["manager"]}),
    ("roadmap_dates", "Set roadmap dates", {"standard": ["manager"], "open": ["manager", "contributor"], "strict": ["manager"]}),
    (None, "Manage releases and sprints", {"standard": ["manager"], "open": ["manager"], "strict": ["manager"]}),
]
# The edges each editable action covers; the roles that may take it are the project's own choice under Custom.
CUSTOM_EDGES = {"forward": FORWARD, "return": RETURN, "complete": COMPLETE, "lifecycle": LIFECYCLE}
CUSTOM_ACTIONS = [key for key, _label, _rows in MATRIX if key]
CUSTOM_ROLES = ("contributor", "reviewer")
ROLE_NAMES = {"manager": "Project Manager", "contributor": "Contributor", "reviewer": "Reviewer"}


class ProjectProject(models.Model):
    _inherit = "project.project"

    agile_permission_scheme = fields.Selection(
        SCHEMES, string="Permission scheme", default="standard", required=True, copy=True
    )

    agile_permission_custom = fields.Json(
        string="Custom permissions", copy=True,
        help="Under the Custom scheme: for each kind of action, which of Contributor and Reviewer may take it.",
    )

    def _agile_custom_grants(self):
        """The Custom scheme as {action: {roles}}; an action never saved starts as Standard has it."""
        self.ensure_one()
        saved = self.agile_permission_custom or {}
        grants = {}
        for key, _label, rows in MATRIX:
            if key:
                roles = saved.get(key) if isinstance(saved.get(key), list) else rows["standard"]
                grants[key] = {role for role in roles if role in CUSTOM_ROLES}
        return grants

    def _agile_edges(self, role):
        """The (from, to) status moves this role may make under the project's scheme."""
        scheme = self.agile_permission_scheme or "standard"
        if scheme == "custom":
            if role == "manager":
                return EVERYTHING
            edges = set()
            for key, roles in self._agile_custom_grants().items():
                if role in roles and key in CUSTOM_EDGES:
                    edges |= CUSTOM_EDGES[key]
            return edges
        return EDGES[scheme].get(role, set())

    def _agile_allows(self, action, user=None):
        """Whether the user's role may take a scheme-controlled action; managers always may."""
        self.ensure_one()
        role = self._agile_role_for_user(user or self.env.user)
        if role == "manager":
            return True
        scheme = self.agile_permission_scheme or "standard"
        if scheme == "custom":
            return role in self._agile_custom_grants()[action]
        return role in ACTION_ROLES[action][scheme]

    def write(self, vals):
        if "agile_permission_scheme" not in vals and "agile_permission_custom" not in vals:
            return super().write(vals)
        if not self.env.su:
            for project in self:
                if project.agile_enabled and not self.env.user.has_group("base.group_system") and (
                    project._agile_role_for_user(self.env.user) != "manager"
                ):
                    raise AccessError(_("Only this project's Agile Manager can change its permission scheme."))
        old = {project.id: project.agile_permission_scheme for project in self}
        result = super().write(vals)
        labels = dict(SCHEMES)
        for project in self:
            if "agile_permission_scheme" in vals and old[project.id] != project.agile_permission_scheme:
                project.sudo().message_post(
                    body=_(
                        "%(user)s switched the permission scheme from %(old)s to %(new)s.",
                        user=self.env.user.name, old=labels[old[project.id]],
                        new=labels[project.agile_permission_scheme],
                    ),
                    message_type="notification", subtype_xmlid="mail.mt_note",
                )
                project._agile_audit("permissions", _(
                    "Switched the permission scheme from %(old)s to %(new)s.",
                    old=labels[old[project.id]], new=labels[project.agile_permission_scheme],
                ))
        return result

    def agile_set_custom_permissions(self, grants):
        """Save the Custom scheme and switch to it; ``grants`` is {action: [roles]} for Contributor and Reviewer."""
        self.ensure_one()
        if not isinstance(grants, dict) or set(grants) - set(CUSTOM_ACTIONS):
            raise UserError(_("Choose from the actions listed on the Permissions page."))
        clean = {}
        for key in CUSTOM_ACTIONS:
            roles = grants.get(key, [])
            if not isinstance(roles, list) or set(roles) - set(CUSTOM_ROLES):
                raise UserError(_("Only Contributor and Reviewer can be changed. Managers always may and stakeholders read only."))
            clean[key] = [role for role in CUSTOM_ROLES if role in roles]
        before = self._agile_custom_grants() if self.agile_permission_scheme == "custom" else None
        self.write({"agile_permission_scheme": "custom", "agile_permission_custom": clean})
        if before is not None and before != self._agile_custom_grants():
            self._agile_audit("permissions", _("Changed the custom permission scheme."))
            self.sudo().message_post(
                body=_("%(user)s changed the custom permission scheme.", user=self.env.user.name),
                message_type="notification", subtype_xmlid="mail.mt_note",
            )

    def action_open_agile_permissions(self):
        self.ensure_one()
        self.check_access("read")
        if not self.agile_enabled:
            raise AccessError(_("Permissions are available only on Agile-enabled projects."))
        if not self.env.user.has_group("base.group_system") and self._agile_role_for_user(self.env.user) != "manager":
            raise AccessError(_("Only this project's Agile Manager can open its permissions."))
        return {
            "type": "ir.actions.client", "tag": "agile_community.permissions", "name": _("Permissions"),
            "params": {"project_id": self.id},
            "context": {"active_id": self.id, "default_project_id": self.id},
        }


class AgilePermissions(models.AbstractModel):
    _name = "agile.permissions"
    _description = "Agile permissions page"

    @api.model
    def _project(self, project_id):
        project = self.env["project.project"].browse(project_id).exists()
        if not project or not project.agile_enabled:
            raise UserError(_("Choose an Agile project."))
        project.check_access("read")
        if not self.env.user.has_group("base.group_system") and project._agile_role_for_user(self.env.user) != "manager":
            raise AccessError(_("Only this project's Agile Manager can open its permissions."))
        return project

    @api.model
    def permissions_data(self, project_id):
        project = self._project(project_id)
        return {
            "project": {"id": project.id, "name": project.name},
            "scheme": project.agile_permission_scheme,
            "schemes": [
                {"key": key, "label": str(_(label)), "sentence": str(_(SCHEME_SENTENCES[key]))}
                for key, label in SCHEMES
            ],
            "matrix": {
                scheme: [
                    {
                        "key": key, "action": str(_(label)),
                        "roles": [str(_(ROLE_NAMES[r])) for r in self._roles_for(project, scheme, key, rows)],
                        "editable": scheme == "custom" and bool(key),
                        "grants": sorted(project._agile_custom_grants().get(key, ())) if key else [],
                    }
                    for key, label, rows in MATRIX
                ]
                for scheme, _label in SCHEMES
            },
            "can_change": True,
        }

    @api.model
    def _roles_for(self, project, scheme, key, rows):
        if scheme != "custom":
            return rows[scheme]
        if not key:
            return ["manager"]
        return ["manager"] + [role for role in CUSTOM_ROLES if role in project._agile_custom_grants()[key]]

    @api.model
    def set_custom(self, project_id, grants):
        project = self._project(project_id)
        project.agile_set_custom_permissions(grants)
        return self.permissions_data(project_id)

    @api.model
    def set_scheme(self, project_id, scheme):
        project = self._project(project_id)
        if scheme not in dict(SCHEMES):
            raise UserError(_("Choose one of the permission schemes."))
        project.write({"agile_permission_scheme": scheme})
        return self.permissions_data(project_id)


class ProjectTask(models.Model):
    _inherit = "project.task"

    agile_restricted = fields.Boolean(
        string="Restricted", copy=False, index=True, tracking=False,
        help="Only the people named here, the assignees, the reporter and project managers can open this issue.",
    )
    agile_visible_user_ids = fields.Many2many(
        "res.users", "agile_task_visible_user_rel", "task_id", "user_id", string="Who can see it", copy=False,
        domain="[('share', '=', False)]",
    )
    agile_member_user_ids = fields.Many2many(
        "res.users", compute="_compute_agile_member_user_ids", string="Team members"
    )
    agile_can_restrict = fields.Boolean(compute="_compute_agile_can_restrict")
    agile_lock_text = fields.Char(string="Restricted", compute="_compute_agile_lock_text")

    @api.depends("project_id.agile_member_ids.user_id")
    def _compute_agile_member_user_ids(self):
        # The form domain cannot walk project_id on an unsaved record, so it filters on this list.
        for task in self:
            task.agile_member_user_ids = task.project_id.sudo().agile_member_ids.user_id

    @api.depends_context("uid")
    @api.depends("project_id.agile_member_ids.role", "create_uid")
    def _compute_agile_can_restrict(self):
        for task in self:
            project = task.project_id
            task.agile_can_restrict = bool(
                task.agile_issue and project.agile_enabled and (
                    not task.id or task.create_uid == self.env.user or project._agile_role_for_user(self.env.user) == "manager"
                    or self.env.user.has_group("base.group_system")
                )
            )

    @api.depends("agile_restricted")
    def _compute_agile_lock_text(self):
        for task in self:
            task.agile_lock_text = _("Restricted") if task.agile_restricted else False

    def _agile_allowed_users(self):
        """Everyone who may open this issue when it is restricted."""
        self.ensure_one()
        managers = self.project_id.sudo().agile_member_ids.filtered(lambda m: m.role == "manager").user_id
        return self.agile_visible_user_ids | self.user_ids | self.create_uid | managers

    def _agile_visible_to(self, users):
        """The users who may open this issue."""
        self.ensure_one()
        if not self.agile_restricted:
            return users
        return users & self._agile_allowed_users()

    @api.constrains("agile_visible_user_ids", "project_id")
    def _check_agile_visible_users(self):
        for task in self.filtered("agile_visible_user_ids"):
            for user in task.agile_visible_user_ids:
                if task.project_id._agile_role_for_user(user) == "none":
                    raise ValidationError(_("%(user)s is not on this project's Agile team.", user=user.name))

    def _agile_check_restrict_permission(self):
        if self.env.su:
            return
        for task in self:
            project = task.project_id
            if not project.agile_enabled:
                raise AccessError(_("Only Agile issues can be restricted."))
            allowed = (
                self.env.user.has_group("base.group_system")
                or project._agile_role_for_user(self.env.user) == "manager"
                or (task.id and task.create_uid == self.env.user)
            )
            if not allowed:
                raise AccessError(_("Only a project manager or the reporter can restrict this issue."))

    def _agile_drop_hidden_followers(self):
        """A restricted issue is not followed by people who cannot open it."""
        for task in self.sudo().filtered("agile_restricted"):
            allowed_partners = task._agile_allowed_users().partner_id
            stale = task.message_partner_ids - allowed_partners
            if stale:
                task.message_unsubscribe(partner_ids=stale.ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            parent = self.browse(vals["parent_id"]) if vals.get("parent_id") else False
            if parent and parent.sudo().agile_restricted and "agile_restricted" not in vals:
                vals["agile_restricted"] = True
                vals["agile_visible_user_ids"] = [Command.set(parent.sudo().agile_visible_user_ids.ids)]
        tasks = super().create(vals_list)
        restricted = tasks.filtered("agile_restricted")
        if restricted:
            restricted._agile_check_restrict_permission()
            restricted._agile_drop_hidden_followers()
        return tasks

    def write(self, vals):
        touching = {"agile_restricted", "agile_visible_user_ids"} & vals.keys()
        if touching:
            self._agile_check_restrict_permission()
        before = {task.id: task.agile_restricted for task in self} if "agile_restricted" in vals else {}
        result = super().write(vals)
        if touching or "user_ids" in vals:
            self._agile_drop_hidden_followers()
        for task in self:
            if "agile_restricted" in vals and before.get(task.id) != task.agile_restricted:
                text = (
                    _("%(user)s restricted this issue.", user=self.env.user.name)
                    if task.agile_restricted
                    else _("%(user)s removed the restriction. Everyone on the project can see this issue.", user=self.env.user.name)
                )
                task.sudo().message_post(
                    body=Markup("%s") % escape(text), message_type="notification", subtype_xmlid="mail.mt_note",
                )
        return result

    def message_subscribe(self, partner_ids=None, subtype_ids=None):
        restricted = self.filtered("agile_restricted") if partner_ids else self.browse()
        if not restricted:
            return super().message_subscribe(partner_ids, subtype_ids)
        for task in restricted:
            allowed = task._agile_allowed_users().partner_id.ids
            super(ProjectTask, task).message_subscribe([pid for pid in partner_ids if pid in allowed], subtype_ids)
        others = self - restricted
        return super(ProjectTask, others).message_subscribe(partner_ids, subtype_ids) if others else True
