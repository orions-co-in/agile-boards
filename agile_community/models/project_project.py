import re
from datetime import datetime, time

import pytz

from odoo import Command, SUPERUSER_ID, api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools.safe_eval import safe_eval


def _agile_timezone_selection(_model):
    return [
        (timezone, timezone)
        for timezone in sorted(
            pytz.all_timezones,
            key=lambda value: value if not value.startswith("Etc/") else "_",
        )
    ]


class ProjectProject(models.Model):
    _inherit = "project.project"

    def _agile_post_audit_note(self, body, area="team"):
        """Post an audit note after the caller's Agile authorization check.

        Project-scoped Agile Managers may have Project read access without
        native Project write access. The audited operation is authorized by
        the Agile policy, so the technical post must not add a second write
        permission requirement. Keep the human actor visible as the author.
        """
        for project in self:
            project.sudo().message_post(
                body=body,
                author_id=self.env.user.partner_id.id,
                subtype_xmlid="mail.mt_note",
            )
        self._agile_audit(area, body)

    def _agile_audit(self, area, text):
        """Hook: agile_pro keeps a project audit log of these notes."""

    agile_enabled = fields.Boolean(
        string="Use Agile", default=False, index=True, tracking=True
    )
    agile_key = fields.Char(
        string="Project Key",
        copy=False,
        index=True,
        tracking=True,
        help="Issue keys use this prefix. It cannot be changed after the first issue is created.",
    )
    agile_method = fields.Selection(
        [("scrum", "Scrum"), ("kanban", "Kanban")],
        string="Work Method",
        default="scrum",
        required=True,
        tracking=True,
        help=(
            "Switching Scrum and Kanban changes planning navigation only. "
            "Issues, workflow history, releases, and completed sprint records remain. "
            "Scrum-only sprint planning is unavailable while Kanban is selected."
        ),
    )
    agile_key_style = fields.Selection(
        [("padded", "Padded (FIT-0001)"), ("plain", "Plain (FIT-1)")],
        string="Issue key style",
        default="padded",
        help="How new issue keys are written. Keys already given do not change, and search finds both forms.",
    )
    agile_timezone = fields.Selection(
        selection=_agile_timezone_selection,
        string="Project Time Zone",
        default=lambda self: self.env.user.tz or "UTC",
        required=True,
        tracking=True,
        help="Used when defaulting calendar dates for sprints in this project.",
    )
    agile_member_ids = fields.One2many(
        "agile.project.member",
        "project_id",
        string="Agile team",
        copy=False,
    )
    agile_wip_limit_ids = fields.One2many(
        "agile.project.wip.limit",
        "project_id",
        string="Workflow WIP limits",
        copy=False,
    )
    can_manage_agile_team = fields.Boolean(compute="_compute_can_manage_agile_team")
    can_manage_project_sprints = fields.Boolean(
        compute="_compute_can_manage_project_sprints"
    )
    can_view_agile_metrics = fields.Boolean(compute="_compute_can_view_agile_metrics")
    agile_configuration_impact = fields.Text(
        string="Configuration impact",
        compute="_compute_agile_configuration_impact",
    )
    agile_open_issue_count = fields.Integer(compute="_compute_agile_dashboard")
    agile_blocked_issue_count = fields.Integer(compute="_compute_agile_dashboard")
    agile_overdue_issue_count = fields.Integer(compute="_compute_agile_dashboard")
    agile_current_sprint_id = fields.Many2one(
        "project.sprint", compute="_compute_agile_dashboard"
    )
    agile_current_sprint_progress = fields.Char(compute="_compute_agile_dashboard")

    def _agile_local_day_start_utc(self):
        today = fields.Date.context_today(self)
        local_midnight = self.env.tz.localize(datetime.combine(today, time.min))
        return local_midnight.astimezone(pytz.UTC).replace(tzinfo=None)

    @api.depends_context("uid")
    @api.depends(
        "agile_enabled",
        "agile_member_ids.user_id",
        "agile_member_ids.role",
    )
    def _compute_can_view_agile_metrics(self):
        for project in self:
            project.can_view_agile_metrics = (
                project.agile_enabled
                and project._agile_role_for_user(self.env.user) != "none"
            )

    @api.depends_context("uid")
    @api.depends(
        "agile_enabled",
        "agile_member_ids.user_id",
        "agile_member_ids.role",
    )
    def _compute_can_manage_agile_team(self):
        for project in self:
            # While Agile is being switched on there is no team yet, so an Odoo
            # Project Manager must see the setup fields to save the first
            # Agile Manager (the same rule write() applies).
            enabling = project.agile_enabled and not project._origin.agile_enabled
            project.can_manage_agile_team = bool(
                project.agile_enabled
                and (
                    project._agile_role_for_user(self.env.user) == "manager"
                    or (
                        enabling
                        and self.env.user.has_group("project.group_project_manager")
                    )
                )
            )

    @api.depends_context("uid")
    @api.depends(
        "agile_enabled",
        "agile_member_ids.user_id",
        "agile_member_ids.role",
    )
    def _compute_can_manage_project_sprints(self):
        for project in self:
            project.can_manage_project_sprints = bool(
                project._agile_role_for_user(self.env.user) == "manager"
                if project.agile_enabled
                else self.env.user.has_group("project.group_project_manager")
            )

    @api.depends("agile_enabled", "agile_method", "agile_timezone")
    def _compute_agile_configuration_impact(self):
        Task = self.env["project.task"]
        Sprint = self.env["project.sprint"]
        Version = self.env["project.version"]
        for project in self:
            if (
                not project.agile_enabled
                or project._agile_role_for_user(self.env.user) != "manager"
            ):
                project.agile_configuration_impact = False
                continue
            domain = [("project_id", "=", project.id)]
            issue_count = Task.search_count(domain + [
                ("agile_issue", "=", True),
                ("active", "=", True),
            ])
            native_count = Task.search_count(domain + [
                ("agile_issue", "=", False),
                ("active", "=", True),
            ])
            sprint_count = Sprint.search_count(domain)
            active_sprint_count = Sprint.search_count(domain + [
                ("state", "=", "in_progress"),
            ])
            release_count = Version.search_count(domain)
            method_effect = (
                _("Scrum planning is available; existing issues are not automatically added to a sprint.")
                if project.agile_method == "scrum"
                else _("Kanban planning is selected; existing sprint records and their history are retained.")
            )
            project.agile_configuration_impact = _(
                "%(method_effect)s Project time zone: %(timezone)s. Current data: %(issues)d active Agile issues, "
                "%(native)d native tasks not yet converted, %(sprints)d sprint records "
                "(%(active_sprints)d active), and %(releases)d releases. Changing the "
                "method does not convert native tasks, delete issues, alter release links, "
                "or rewrite saved sprint/report history. Stage meanings are locked while "
                "issues use them; a blank estimate means unestimated, while zero is a real "
                "estimate and confirmed sprint commitments are unchanged.",
                method_effect=method_effect,
                timezone=project.agile_timezone or "UTC",
                issues=issue_count,
                native=native_count,
                sprints=sprint_count,
                active_sprints=active_sprint_count,
                releases=release_count,
            )

    @api.depends("agile_enabled", "sprint_ids.state", "sprint_ids.task_ids.state")
    def _compute_agile_dashboard(self):
        projects = self.filtered("agile_enabled")
        visible_projects = projects.filtered(
            lambda project: project._agile_role_for_user(self.env.user) != "none"
        )
        empty = {
            project.id: {"open": 0, "blocked": 0, "overdue": 0}
            for project in visible_projects
        }
        if visible_projects:
            task_model = self.env["project.task"]
            base = [
                ("project_id", "in", visible_projects.ids),
                ("agile_issue", "=", True),
                ("active", "=", True),
                ("agile_is_epic", "=", False),
                ("child_ids", "=", False),
            ]
            grouped = task_model._read_group(
                base, ["project_id", "stage_id"], ["__count"]
            )
            for project, stage, count in grouped:
                if stage.agile_status not in ("done", "canceled"):
                    empty[project.id]["open"] += count
            blocked_groups = task_model._read_group(
                base + [
                    ("agile_is_blocked", "=", True),
                    ("stage_id.agile_status", "not in", ["done", "canceled"]),
                ],
                ["project_id"],
                ["__count"],
            )
            for project, count in blocked_groups:
                empty[project.id]["blocked"] = count

            utc_midnight = self._agile_local_day_start_utc()
            overdue_groups = task_model._read_group(
                base + [
                    ("date_deadline", "<", fields.Datetime.to_string(utc_midnight)),
                    ("stage_id.agile_status", "not in", ["done", "canceled"]),
                ],
                ["project_id"],
                ["__count"],
            )
            for project, count in overdue_groups:
                empty[project.id]["overdue"] = count

        for project in self:
            if not project.agile_enabled:
                project.agile_open_issue_count = 0
                project.agile_blocked_issue_count = 0
                project.agile_overdue_issue_count = 0
                project.agile_current_sprint_id = False
                project.agile_current_sprint_progress = False
                continue
            if project not in visible_projects:
                project.agile_open_issue_count = 0
                project.agile_blocked_issue_count = 0
                project.agile_overdue_issue_count = 0
                project.agile_current_sprint_id = False
                project.agile_current_sprint_progress = False
                continue
            totals = empty[project.id]
            project.agile_open_issue_count = totals["open"]
            project.agile_blocked_issue_count = totals["blocked"]
            project.agile_overdue_issue_count = totals["overdue"]
            sprint = project._agile_active_sprints()[:1]
            project.agile_current_sprint_id = sprint
            if sprint:
                sprint_tasks = self.env["project.task"].search(
                    [
                        ("sprint_id", "=", sprint.id),
                        ("agile_issue", "=", True),
                        ("agile_is_epic", "=", False),
                        ("child_ids", "=", False),
                    ]
                )
                done = sprint_tasks.filtered(
                    lambda task: task.agile_status == "done"
                )
                eligible = sprint_tasks.filtered(
                    lambda task: task.agile_status != "canceled"
                )
                project.agile_current_sprint_progress = _(
                    "%(done)s of %(total)s issues complete",
                    done=len(done),
                    total=len(eligible),
                )
            else:
                project.agile_current_sprint_progress = _("No active sprint")

    def action_view_agile_metric_issues(self):
        self.ensure_one()
        self._check_agile_metrics_access()
        metric = self.env.context.get("agile_metric_filter", "open")
        domain = self._agile_metric_domain(metric)
        titles = {
            "open": _("Open Issues"),
            "blocked": _("Blocked Issues"),
            "overdue": _("Overdue Issues"),
            "review": _("Issues In Review"),
            "unassigned": _("Unassigned Issues"),
            "unestimated": _("Unestimated Issues"),
        }
        return {
            "type": "ir.actions.act_window",
            "name": titles.get(metric, _("Agile Issues")),
            "res_model": "project.task",
            "view_mode": "list,kanban,form",
            "domain": domain,
            "context": {
                "default_project_id": self.id,
                "search_default_open_tasks": 0,
            },
        }

    def action_view_agile_current_sprint(self):
        self.ensure_one()
        self._check_agile_metrics_access()
        if not self.agile_current_sprint_id:
            return self.action_view_agile_metric_issues()
        return self.agile_current_sprint_id.action_tasks()

    def _check_agile_roadmap_access(self):
        self.ensure_one()
        self.check_access("read")
        role = self._agile_role_for_user(self.env.user)
        if not self.agile_enabled or role == "none":
            if self.agile_enabled:
                raise AccessError(_("You are not a member of this Agile project."))
            raise UserError(_("Enable Agile on this project to open its roadmap."))

    def action_view_agile_roadmap(self):
        self.ensure_one()
        self._check_agile_roadmap_access()
        return {
            "type": "ir.actions.act_window",
            "name": _("Project Roadmap"),
            "res_model": "agile.roadmap.item",
            "view_mode": "timeline,list,form",
            "views": [
                (self.env.ref("agile_community.agile_roadmap_item_timeline").id, "timeline"),
                (self.env.ref("agile_community.agile_roadmap_item_list").id, "list"),
                (self.env.ref("agile_community.agile_roadmap_item_form").id, "form"),
            ],
            "domain": [("project_id", "=", self.id)],
            "context": {"create": False},
        }

    def action_view_agile_unscheduled_issues(self):
        self.ensure_one()
        self._check_agile_roadmap_access()
        return {
            "type": "ir.actions.act_window",
            "name": _("Unscheduled Agile Issues"),
            "res_model": "project.task",
            "view_mode": "list,form",
            "views": [
                (self.env.ref("agile_community.project_task_list_agile_backlog_order").id, "list"),
                (False, "form"),
            ],
            "search_view_id": self.env.ref("agile_community.project_task_search_agile").id,
            "domain": [
                ("project_id", "=", self.id),
                ("agile_issue", "=", True),
                ("active", "=", True),
                "|",
                ("agile_planned_start", "=", False),
                ("agile_planned_end", "=", False),
            ],
            "context": {"default_project_id": self.id, "create": False},
        }

    def action_view_agile_roadmap_epics(self):
        self.ensure_one()
        self._check_agile_roadmap_access()
        return {
            "type": "ir.actions.act_window",
            "name": _("Epic Roadmap List"),
            "res_model": "project.task",
            "view_mode": "list,form",
            "views": [
                (self.env.ref("agile_community.project_task_epic_roadmap_list").id, "list"),
                (False, "form"),
            ],
            "search_view_id": self.env.ref("agile_community.project_task_search_agile").id,
            "domain": [
                ("project_id", "=", self.id),
                ("agile_issue", "=", True),
                ("active", "=", True),
                ("agile_task_type_id.is_epic", "=", True),
            ],
            "help": _(
                "<p class='o_view_nocontent_smiling_face'>No Epics yet</p>"
                "<p>Use New to create an Epic, then link issues to it as children.</p>"
            ),
            "context": {
                "default_project_id": self.id,
                "default_agile_task_type_id": self.env.ref(
                    "agile_community.agile_task_type_epic"
                ).id,
            },
        }

    def action_view_agile_reports(self):
        self.ensure_one()
        self._check_agile_metrics_access()
        return {
            "type": "ir.actions.act_window",
            "name": _("Agile Delivery History"),
            "res_model": "agile.metric.snapshot.line",
            "view_mode": "graph,pivot,list",
            "domain": [("project_id", "=", self.id)],
            "context": {
                "default_project_id": self.id,
                "graph_measure": "remaining_points",
            },
        }

    def _check_agile_metrics_access(self):
        self.ensure_one()
        self.check_access("read")
        if not self.agile_enabled:
            raise UserError(_("Enable Agile on this project to open its delivery metrics."))
        if self._agile_role_for_user(self.env.user) == "none":
            raise AccessError(
                _("You must be a member of this Agile project to view its delivery metrics.")
            )

    @api.model
    def _agile_user_is_odoo_admin(self, user=None):
        """True when the user's Odoo groups give an implicit manager role on every Agile project."""
        user = user or self.env.user
        if user.id == SUPERUSER_ID:
            return True
        if user.agile_is_agent:
            # Agents never inherit the ceiling; they need a team row.
            return False
        return user.has_group("base.group_system") or user.has_group(
            "agile_community.group_agile_admin"
        )

    def _agile_access(self, user=None):
        """Return (role, source) of the user on this project.

        source is 'odoo_admin' (implicit manager from Odoo groups), 'team' (team row) or 'none'.
        The implicit role is a ceiling: a team row never lowers it.
        """
        self.ensure_one()
        user = user or self.env.user
        if not self.agile_enabled:
            return "none", "none"
        if self._agile_user_is_odoo_admin(user):
            return "manager", "odoo_admin"
        member = self.env["agile.project.member"].sudo().search([
            ("project_id", "=", self.id),
            ("user_id", "=", user.id),
        ], limit=1)
        if member.role:
            return member.role, "team"
        return "none", "none"

    def _agile_access_by_project(self, user=None):
        """Batch form of _agile_access: {project id: (role, source)} in one query.

        Same rule as the single resolver, so lists and detail views cannot disagree.
        """
        user = user or self.env.user
        enabled = self.filtered("agile_enabled")
        result = {project.id: ("none", "none") for project in self}
        if not enabled:
            return result
        if self._agile_user_is_odoo_admin(user):
            result.update({project.id: ("manager", "odoo_admin") for project in enabled})
            return result
        members = self.env["agile.project.member"].sudo().search([
            ("project_id", "in", enabled.ids),
            ("user_id", "=", user.id),
        ])
        result.update({member.project_id.id: (member.role, "team") for member in members if member.role})
        return result

    def _agile_role_for_user(self, user=None):
        return self._agile_access(user)[0]

    def action_manage_agile_team(self):
        self.ensure_one()
        self.check_access("read")
        if self._agile_role_for_user(self.env.user) != "manager":
            raise AccessError(_("Only this project's manager can manage its Agile team."))
        # _for_xml_id reads the action as the system, so a project manager who is not an Odoo
        # administrator can open it (reading ir.actions.act_window directly is admin-only).
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "agile_community.action_agile_project_member"
        )
        action["domain"] = [("project_id", "=", self.id)]
        action["context"] = {"default_project_id": self.id}
        return action

    def action_view_unconverted_agile_tasks(self):
        self.ensure_one()
        self.check_access("read")
        if self._agile_role_for_user(self.env.user) != "manager":
            raise AccessError(
                _("Only this project's Agile Manager can prepare existing tasks.")
            )
        return {
            "type": "ir.actions.act_window",
            "name": _("Existing tasks to prepare"),
            "res_model": "project.task",
            "view_mode": "list,form",
            "domain": [
                ("project_id", "=", self.id),
                ("agile_issue", "=", False),
            ],
            "context": {"default_project_id": self.id, "agile_unconverted_list": True},
        }

    def action_manage_agile_issue_types(self):
        self.ensure_one()
        self.check_access("read")
        if (
            not self.agile_enabled
            or self._agile_role_for_user(self.env.user) != "manager"
        ):
            raise AccessError(
                _("Only this project's Agile Manager can manage its issue types.")
            )
        return {
            "type": "ir.actions.act_window",
            "name": _("Project Issue Types"),
            "res_model": "agile_community.task_type",
            "view_mode": "list,form",
            "domain": [("project_ids", "in", self.id)],
            "context": {
                "default_project_ids": [(6, 0, [self.id])],
                "default_company_id": self.company_id.id or False,
                # Keep the Agile sidebar around this settings screen (NU-46).
                "default_project_id": self.id,
                "agile_sidebar_entry": "settings",
            },
        }

    def _initialize_agile_team_roles(self):
        """Preserve current global-group access when an Agile team is enabled."""
        Member = self.env["agile.project.member"].sudo().with_context(
            agile_role_seed=True
        )
        role_groups = [
            ("reviewer", "agile_community.group_agile_reviewer"),
            ("stakeholder", "agile_community.group_agile_stakeholder"),
            ("contributor", "project.group_project_user"),
        ]
        for project in self.filtered("agile_enabled"):
            existing_user_ids = set(
                Member.search([("project_id", "=", project.id)]).mapped("user_id").ids
            )
            role_by_user = {}
            for role, group_xmlid in reversed(role_groups):
                for user in self.env.ref(group_xmlid).all_user_ids:
                    if not user.active:
                        continue
                    if project.company_id and project.company_id not in user.company_ids:
                        continue
                    if not project.with_user(user).has_access("read"):
                        continue
                    if user.has_group("project.group_project_manager"):
                        # Global Project Managers already see every native
                        # project. Do not silently make every one an Agile
                        # team member; the designated project owner is handled
                        # separately below.
                        continue
                    role_by_user[user.id] = role
            owner = project.user_id
            if (
                owner
                and owner.active
                and not owner.share
                and owner.has_group("project.group_project_user")
                and (not project.company_id or project.company_id in owner.company_ids)
                and project.with_user(owner).has_access("read")
            ):
                role_by_user[owner.id] = "manager"
            enabler = self.env.user
            if (
                enabler.id != SUPERUSER_ID
                and enabler.active
                and not enabler.share
                and enabler.has_group("project.group_project_manager")
                and enabler.id not in existing_user_ids
            ):
                # The Project Manager who enables Agile must be able to work in
                # it; otherwise they are locked out of their own project.
                role_by_user[enabler.id] = "manager"
            Member.create([
                {
                    "project_id": project.id,
                    "user_id": user_id,
                    "role": role,
                }
                for user_id, role in role_by_user.items()
                if user_id not in existing_user_ids
            ])

    _agile_key_unique = models.Constraint(
        "unique (agile_key)",
        "Project Key must be unique.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("agile_enabled") and not self.env.user.has_group(
                "project.group_project_manager"
            ):
                raise AccessError(
                    _("Only an Odoo Project Manager can enable Agile on a project.")
                )
            if vals.get("agile_key"):
                vals["agile_key"] = vals["agile_key"].strip().upper()
            if vals.get("agile_enabled"):
                vals["use_scrum"] = vals.get("agile_method", "scrum") == "scrum"
        projects = super().create(vals_list)
        agile_projects = projects.filtered("agile_enabled")
        agile_projects._ensure_agile_issue_sequence()
        agile_projects._ensure_agile_workflow_stages()
        agile_projects._initialize_agile_team_roles()
        return projects

    def write(self, vals):
        if "agile_enabled" in vals and any(
            project.agile_enabled != vals["agile_enabled"] for project in self
        ) and not self.env.user.has_group("project.group_project_manager"):
            raise AccessError(
                _("Only an Odoo Project Manager can enable or disable Agile.")
            )
        if {"agile_key", "agile_key_style", "agile_method", "agile_timezone", "agile_git_enabled", "agile_git_secret", "agile_git_smart_commits", "agile_hook_enabled", "agile_hook_url", "agile_hook_format"} & vals.keys():
            protected_projects = self.filtered("agile_enabled")
            protected_projects |= self.filtered(
                lambda project: vals.get("agile_enabled", project.agile_enabled)
            )
            if any(
                project._agile_role_for_user(self.env.user) != "manager"
                for project in protected_projects
                if not (
                    not project.agile_enabled
                    and vals.get("agile_enabled")
                    and self.env.user.has_group("project.group_project_manager")
                )
            ):
                raise AccessError(
                    _("Only this project's Agile Manager can change its Agile settings.")
                )
        newly_enabled = self.filtered(
            lambda project: vals.get("agile_enabled") and not project.agile_enabled
        )
        if vals.get("agile_key"):
            vals = {**vals, "agile_key": vals["agile_key"].strip().upper()}
        if "agile_key" in vals:
            for project in self:
                if (
                    project.agile_key
                    and vals["agile_key"] != project.agile_key
                    and self.env["project.task"].search_count([
                        ("project_id", "=", project.id),
                        ("issue_key", "!=", False),
                    ])
                ):
                    raise ValidationError(
                        _("Project Key cannot be changed after the first Agile issue is created.")
                    )
        sync_scrum = "agile_enabled" in vals or "agile_method" in vals
        if sync_scrum:
            result = True
            for project in self:
                enabled = vals.get("agile_enabled", project.agile_enabled)
                method = vals.get("agile_method", project.agile_method)
                project_vals = dict(vals)
                if enabled or "agile_enabled" in vals:
                    project_vals["use_scrum"] = bool(enabled and method == "scrum")
                result = super(ProjectProject, project).write(project_vals) and result
        else:
            result = super().write(vals)
        agile_projects = self.filtered("agile_enabled")
        agile_projects._ensure_agile_issue_sequence()
        if "agile_key_style" in vals:
            for project in agile_projects:
                sequence = self.env["ir.sequence"].sudo().search(
                    [("code", "=", f"agile_community.issue_{project.id}")], limit=1
                )
                sequence.padding = 0 if project.agile_key_style == "plain" else 4
        if vals.get("agile_enabled"):
            agile_projects._ensure_agile_workflow_stages()
        newly_enabled._initialize_agile_team_roles()
        return result

    @api.constrains("agile_enabled", "agile_method", "use_scrum")
    def _check_scrum_method(self):
        for project in self.filtered("agile_enabled"):
            if project.use_scrum != (project.agile_method == "scrum"):
                raise ValidationError(
                    _("Scrum planning must match the Agile project work method.")
                )

    def action_view_tasks(self):
        self.check_access("read")
        # Core loads its stored action with active_id set; without the flag the
        # URL-reload hook in ir.actions.act_window would re-enter this method.
        action = super(
            ProjectProject, self.with_context(agile_tasks_action_resolved=True)
        ).action_view_tasks()
        if self.agile_enabled:
            domain = action.get("domain") or []
            if isinstance(domain, str):
                domain = safe_eval(domain, {"active_id": self.id})
            action["domain"] = domain + [
                ("agile_issue", "=", True)
            ]
            ordered_kanban = self.env.ref(
                "agile_community.project_task_kanban_agile_backlog_order"
            ).id
            ordered_list = self.env.ref(
                "agile_community.project_task_list_agile_backlog_order"
            ).id
            action["views"] = [
                (
                    ordered_kanban
                    if view_type == "kanban"
                    else ordered_list
                    if view_type == "list"
                    else view_id,
                    view_type,
                )
                for view_id, view_type in action["views"]
            ]
            action["context"].pop("search_default_open_tasks", None)
            action["context"]["agile_project_view"] = True
            # Epic children are issues, not sub-tasks; core hides sub-tasks unless asked.
            action["context"]["subtask_action"] = True
            action["context"]["agile_wip_limit_display"] = True
            action["context"]["default_project_id"] = self.id
            action["context"]["agile_scrum_mode"] = self.agile_method == "scrum"
            if self.agile_method != "scrum" and not self.agile_kanban_backlog_column:
                action["context"]["agile_hide_backlog_column"] = True
            if self.agile_method == "scrum" or not self.agile_kanban_backlog_column:
                # The backlog lives on its own screen, not as a board column (B-401).
                # A Kanban project can ask for a Backlog column too (R-1105).
                action["domain"] = action["domain"] + [
                    ("stage_id.agile_status", "!=", "backlog")
                ]
            action["context"]["agile_drawer_view_id"] = self.env.ref(
                "agile_community.view_project_task_form_agile_drawer"
            ).id
            if self.agile_method == "scrum":
                active_sprints = self._agile_active_sprints()
                if active_sprints:
                    action["context"]["search_default_agile_active_sprint"] = 1
                    # Issues created on the board join the sprint they are looking at;
                    # only managers may place issues in a sprint. With several active
                    # sprints there is no single one to join, so no default is set.
                    if self._agile_role_for_user() == "manager" and len(active_sprints) == 1:
                        action["context"]["default_sprint_id"] = active_sprints.id
            action["search_view_id"] = self.env.ref(
                "agile_community.project_task_search_agile"
            ).id
            action = self._agile_apply_view_preference(action)
            role = self._agile_role_for_user()
            if role == "stakeholder" or role == "none":
                action["context"].update({
                    "create": False,
                    "edit": False,
                    "delete": False,
                })
            # The stored action's help was worked out before agile_scrum_mode was in the context (E2E-013).
            action["help"] = self.env["project.task"].with_context(
                **action["context"]
            ).get_empty_list_help(action.get("help") or "")
        return action

    def _ensure_agile_workflow_stages(self):
        """Seed Agile stages once without rewriting existing native tasks."""
        stage_model = self.env["project.task.type"].sudo()
        definitions = [
            ("backlog", "Backlog", 10, False),
            ("ready", "To Do", 20, False),
            ("progress", "In Progress", 30, False),
            ("review", "Review", 40, False),
            ("done", "Done", 50, False),
            ("canceled", "Canceled", 60, True),
        ]
        for project in self:
            stages_by_status = {
                stage.agile_status: stage
                for stage in stage_model.with_context(active_test=False).search([
                    ("project_ids", "=", project.id),
                    ("agile_status", "!=", False),
                ])
            }
            for status, name, sequence, fold in definitions:
                if status not in stages_by_status:
                    stages_by_status[status] = stage_model.create({
                        "name": name,
                        "sequence": sequence,
                        "fold": fold,
                        "agile_status": status,
                        "project_ids": [Command.link(project.id)],
                    })

            project._ensure_agile_default_workflow()

            # Existing task stages and project associations are left untouched.
            # A manager must explicitly map selected tasks through the conversion wizard.

    def _ensure_agile_issue_sequence(self):
        sequence_model = self.env["ir.sequence"].sudo()
        for project in self:
            if not project.agile_key:
                continue
            # Serialize first-use provisioning for projects upgraded from the
            # base feature, which did not yet have per-project sequences.
            self.env.cr.execute(
                "SELECT pg_advisory_xact_lock(%s, %s)",
                (1095190860, project.id),
            )
            code = f"agile_community.issue_{project.id}"
            if not sequence_model.search_count([("code", "=", code)]):
                highest_number = 0
                prefix = f"{project.agile_key}-"
                existing_keys = self.env["project.task"].sudo().search([
                    ("project_id", "=", project.id),
                    ("issue_key", "like", f"{prefix}%"),
                ]).mapped("issue_key")
                for issue_key in existing_keys:
                    suffix = issue_key.removeprefix(prefix)
                    if suffix.isdigit():
                        highest_number = max(highest_number, int(suffix))
                sequence_model.create({
                    "name": f"Agile issues — {project.agile_key}",
                    "code": code,
                    "prefix": f"{project.agile_key}-",
                    "padding": 4 if project.agile_key_style != "plain" else 0,
                    "number_next": highest_number + 1,
                    "company_id": project.company_id.id or False,
                    "implementation": "no_gap",
                })

    @api.constrains("agile_enabled", "agile_key")
    def _check_agile_key(self):
        for project in self:
            if not project.agile_enabled:
                continue
            if not project.agile_key or not re.fullmatch(r"[A-Z][A-Z0-9]{1,9}", project.agile_key):
                raise ValidationError(_("Project Key must be 2–10 uppercase letters or digits, starting with a letter."))
            duplicate = self.with_context(active_test=False).search_count([
                ("id", "!=", project.id),
                ("agile_enabled", "=", True),
                ("agile_key", "=", project.agile_key),
            ])
            if duplicate:
                raise ValidationError(_("Project Key must be unique across Agile projects."))
