from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError


class ProjectVersion(models.Model):
    _inherit = "project.version"

    description = fields.Text()
    release_date = fields.Date(string="Target date")
    state = fields.Selection(
        [("planned", "Planned"), ("released", "Released")],
        default="planned",
        required=True,
        copy=False,
    )
    active = fields.Boolean(default=True)
    task_ids = fields.One2many("project.task", "version_id", string="Assigned tasks")
    agile_issue_ids = fields.One2many(
        "project.task",
        "version_id",
        string="Included issues",
        domain=[("project_id.agile_enabled", "=", True), ("agile_is_epic", "=", False)],
    )
    affected_issue_ids = fields.Many2many(
        "project.task",
        "agile_task_affects_version_rel",
        "version_id",
        "task_id",
        string="Issues found in this release",
    )
    affected_issue_count = fields.Integer(compute="_compute_affected_issue_count")
    milestone_id = fields.Many2one(
        "project.milestone",
        string="Linked milestone",
        domain="[('project_id', '=', project_id)]",
        ondelete="restrict",
        help="Optional planning link. Releasing this version does not complete the milestone.",
    )
    is_agile_release = fields.Boolean(
        related="project_id.agile_enabled", string="Agile release"
    )
    can_manage_agile_release = fields.Boolean(
        compute="_compute_can_manage_agile_release"
    )
    released_by_id = fields.Many2one("res.users", readonly=True, copy=False)
    released_at = fields.Datetime(readonly=True, copy=False)
    issue_count = fields.Integer(compute="_compute_issue_summary")
    open_issue_count = fields.Integer(compute="_compute_issue_summary")
    done_issue_count = fields.Integer(compute="_compute_issue_summary")
    canceled_issue_count = fields.Integer(compute="_compute_issue_summary")
    is_ready = fields.Boolean(compute="_compute_issue_summary")
    audit_ids = fields.One2many(
        "agile_community.release_audit", "release_id", string="History"
    )

    @api.constrains("name", "project_id", "active")
    def _check_agile_release_name_unique(self):
        for release in self.filtered(lambda r: r.project_id.agile_enabled and r.active and r.name):
            name = release.name.strip().lower()
            twins = self.with_context(active_test=True).search(
                [("project_id", "=", release.project_id.id), ("id", "!=", release.id)]
            )
            if any((twin.name or "").strip().lower() == name for twin in twins):
                raise ValidationError(
                    _(
                        "A release named %(name)s already exists in this project. Use a different name.",
                        name=release.name,
                    )
                )

    @api.depends_context("uid")
    @api.depends(
        "project_id.agile_enabled",
        "project_id.agile_member_ids.user_id",
        "project_id.agile_member_ids.role",
    )
    def _compute_can_manage_agile_release(self):
        for release in self:
            release.can_manage_agile_release = bool(
                release.is_agile_release
                and release.project_id._agile_role_for_user(self.env.user) == "manager"
            )

    @api.depends(
        "project_id.agile_enabled",
        "task_ids.project_id",
        "task_ids.stage_id",
        "task_ids.stage_id.agile_status",
    )
    def _compute_issue_summary(self):
        # During form onchange the records are virtual; key everything by the saved id.
        counts = {
            release._origin.id: {"done": 0, "canceled": 0, "open": 0}
            for release in self
        }
        groups = self.env["project.task"]._read_group(
            [
                ("version_id", "in", [rid for rid in counts if rid]),
                ("project_id.agile_enabled", "=", True),
                ("agile_issue", "=", True),
                ("agile_is_epic", "=", False),
            ],
            ["version_id", "stage_id"],
            ["__count"],
        )
        for release, stage, count in groups:
            status = stage.agile_status if stage else False
            bucket = status if status in ("done", "canceled") else "open"
            counts[release.id][bucket] += count
        for release in self:
            summary = counts[release._origin.id]
            release.done_issue_count = summary["done"]
            release.canceled_issue_count = summary["canceled"]
            release.open_issue_count = summary["open"]
            release.issue_count = sum(summary.values())
            release.is_ready = release.issue_count > 0 and release.open_issue_count == 0

    @api.constrains("milestone_id", "project_id")
    def _check_milestone_project(self):
        for release in self:
            if release.milestone_id and release.milestone_id.project_id != release.project_id:
                raise ValidationError(
                    _("A release can only link to a milestone in the same project.")
                )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            project_id = vals.get("project_id") or self.env.context.get("default_project_id")
            project = self.env["project.project"].browse(project_id)
            if project.agile_enabled:
                self._ensure_manager(project=project)
                if vals.get("state", "planned") != "planned":
                    raise ValidationError(_("Create a release as Planned, then release it explicitly."))
                if vals.get("released_by_id") or vals.get("released_at"):
                    raise ValidationError(_("Release actor and time are set only by the release action."))
        releases = super().create(vals_list)
        for release in releases.filtered("is_agile_release"):
            release._log_event("created", new_values=release._audit_snapshot())
        return releases

    def write(self, vals):
        agile = self.filtered("is_agile_release")
        target_project = self.env["project.project"].browse(vals["project_id"]) if vals.get("project_id") else self.env["project.project"]
        protected_projects = agile.mapped("project_id") | target_project.filtered("agile_enabled")
        if protected_projects:
            self._ensure_manager(projects=protected_projects)
        if "project_id" in vals:
            moving = agile.filtered(
                lambda version: version.project_id.id != vals["project_id"]
            )
            referenced = self.env["project.task"].sudo().with_context(
                active_test=False
            ).search_count([
                ("version_id", "in", moving.ids),
                ("agile_issue", "=", True),
            ])
            if referenced:
                raise UserError(
                    _(
                        "A Fix Version assigned to Agile issues cannot be moved to another project. "
                        "Create a version in the destination project instead."
                    )
                )
        if agile:
            if "state" in vals or "released_by_id" in vals or "released_at" in vals:
                raise UserError(_("Use the release action to change release status."))
            if agile.filtered(lambda release: release.state == "released"):
                raise UserError(_("A released record is locked. Use its correction action."))
        return super().write(vals)

    def unlink(self):
        agile = self.filtered("is_agile_release")
        if agile:
            self._ensure_manager(projects=agile.mapped("project_id"))
            raise UserError(_("Archive the release to preserve its history and issue targets."))
        return super().unlink()

    def _ensure_manager(self, project=False, projects=False):
        projects = projects or (self.mapped("project_id") if self else project)
        if not self.env.su and any(
            not agile_project.with_user(self.env.user).has_access("read")
            for agile_project in projects
        ):
            raise AccessError(
                _("You must retain native Odoo Project access to manage its releases.")
            )
        if any(
            not agile_project.agile_enabled
            or agile_project._agile_role_for_user(self.env.user) != "manager"
            for agile_project in projects
        ):
            raise AccessError(
                _("Only a Project Manager for this Agile project can manage its releases.")
            )

    def _audit_snapshot(self):
        self.ensure_one()
        return {
            "name": self.name,
            "target_date": fields.Date.to_string(self.release_date) if self.release_date else False,
            "description": self.description or False,
            "milestone_id": self.milestone_id.id or False,
        }

    def _log_event(self, event_type, reason=False, previous_values=None, new_values=None, issue=False):
        self.ensure_one()
        self.env["agile_community.release_audit"].sudo().create({
            "release_id": self.id,
            "event_type": event_type,
            "actor_id": self.env.user.id,
            "event_date": fields.Datetime.now(),
            "reason": reason,
            "previous_values": previous_values or {},
            "new_values": new_values or {},
            "issue_id": issue.id if issue else False,
        })

    def action_agile_open_release_confirm(self):
        """Mark as Released starts here: the dialog counts the open issues and offers to move them (NU-12)."""
        self.ensure_one()
        self._ensure_manager()
        if self.state != "planned":
            raise UserError(_("Only a planned release can be released."))
        wizard = self.env["agile.release.confirm"].create({"release_id": self.id})
        return {
            "type": "ir.actions.act_window",
            "name": _("Mark as Released"),
            "res_model": "agile.release.confirm",
            "res_id": wizard.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_release(self):
        self.ensure_one()
        self._ensure_manager()
        if not self.is_agile_release:
            raise UserError(_("Only Agile releases use this action."))
        if self.state != "planned":
            raise UserError(_("Only a planned release can be released."))
        self.env.cr.execute("SELECT id FROM project_version WHERE id = %s FOR UPDATE", [self.id])
        self.invalidate_recordset(["state", "issue_count", "open_issue_count"])
        if self.state != "planned":
            raise UserError(_("Only a planned release can be released."))
        previous = self._audit_snapshot()
        now = fields.Datetime.now()
        super(ProjectVersion, self).write({
            "state": "released",
            "released_by_id": self.env.user.id,
            "released_at": now,
        })
        self._log_event(
            "released",
            previous_values=previous,
            new_values={
                "state": "released",
                "released_by": self.env.user.display_name,
                "released_at": fields.Datetime.to_string(now),
                "open_issues": self.open_issue_count,
            },
        )
        message = _("Release marked as released.")
        if self.open_issue_count:
            message = _("Release marked as released with %(count)s open issue(s). Review the blocking work below.", count=self.open_issue_count)
        elif not self.issue_count:
            message = _("Release marked as released with no included issues.")
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"title": _("Release updated"), "message": message, "type": "warning" if (self.open_issue_count or not self.issue_count) else "success", "sticky": bool(self.open_issue_count or not self.issue_count)},
        }

    def _release_notes_markdown(self):
        """Markdown notes for the Done issues this user can read, grouped by issue type."""
        self.ensure_one()
        self.check_access("read")
        issues = self.agile_issue_ids
        done = issues.filtered(lambda issue: issue.stage_id.agile_status == "done")
        lines = [f"## {self.name}"]
        if self.release_date:
            lines.append(f"Target date: {fields.Date.to_string(self.release_date)}")
        if self.description:
            lines += ["", self.description.strip()]
        types = done.mapped("agile_task_type_id").sorted(lambda t: (t.sequence, t.id))
        for task_type in types:
            group = done.filtered(lambda issue: issue.agile_task_type_id == task_type)
            lines += ["", f"### {task_type.name} ({len(group)})"]
            lines += [f"- {issue.issue_key}: {issue.name}" for issue in group.sorted("id")]
        untyped = done.filtered(lambda issue: not issue.agile_task_type_id)
        if untyped:
            lines += ["", f"### Other ({len(untyped)})"]
            lines += [f"- {issue.issue_key}: {issue.name}" for issue in untyped.sorted("id")]
        if not done:
            lines += ["", "No finished issues in this release yet."]
        still_open = len(issues) - len(done) - len(
            issues.filtered(lambda issue: issue.stage_id.agile_status == "canceled")
        )
        if still_open:
            lines += ["", f"{still_open} open issue(s) are not included in these notes."]
        return "\n".join(lines)

    def action_open_release_burndown(self):
        self.ensure_one()
        self.check_access("read")
        if not self.is_agile_release:
            raise UserError(_("The burndown is available for Agile releases only."))
        return self.env["agile.report"].report_action(self.project_id.id, "release", self.id)

    def action_open_release_notes(self):
        self.ensure_one()
        self.check_access("read")
        if not self.is_agile_release:
            raise UserError(_("Release notes are available for Agile releases only."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Release notes"),
            "res_model": "agile_community.release_notes_wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_release_id": self.id},
        }

    def action_view_release_issues(self):
        self.ensure_one()
        return self._action_view_issues(blockers_only=False)

    @api.depends("affected_issue_ids")
    def _compute_affected_issue_count(self):
        counts = {
            version.id: count
            for version, count in self.env["project.task"]._read_group(
                [("agile_affects_version_ids", "in", self.ids), ("agile_issue", "=", True)],
                ["agile_affects_version_ids"],
                ["__count"],
            )
        }
        for version in self:
            version.affected_issue_count = counts.get(version.id, 0)

    def action_view_affected_issues(self):
        """Issues that name this release under Affects Versions."""
        self.ensure_one()
        self.check_access("read")
        return {
            "type": "ir.actions.act_window",
            "name": _("Issues found in %(release)s", release=self.name),
            "res_model": "project.task",
            "view_mode": "list,form",
            "views": [
                (self.env.ref("agile_community.project_task_list_agile_backlog_order").id, "list"),
                (False, "form"),
            ],
            "domain": [("agile_affects_version_ids", "in", self.ids), ("agile_issue", "=", True)],
            "context": {"default_project_id": self.project_id.id},
        }

    def action_view_release_blockers(self):
        self.ensure_one()
        return self._action_view_issues(blockers_only=True)

    def _action_view_issues(self, blockers_only):
        self.ensure_one()
        self.check_access("read")
        domain = [
            ("version_id", "=", self.id),
            ("project_id.agile_enabled", "=", True),
            ("agile_issue", "=", True),
        ]
        if blockers_only:
            domain += [("stage_id.agile_status", "not in", ["done", "canceled"])]
        return {
            "type": "ir.actions.act_window",
            "name": _("Open issues blocking %(release)s", release=self.name) if blockers_only else _("Issues in %(release)s", release=self.name),
            "res_model": "project.task",
            "view_mode": "list,form,kanban",
            "views": [
                (
                    self.env.ref(
                        "agile_community.project_task_list_agile_backlog_order"
                    ).id,
                    "list",
                ),
                (False, "form"),
                (
                    self.env.ref(
                        "agile_community.project_task_kanban_agile_backlog_order"
                    ).id,
                    "kanban",
                ),
            ],
            "domain": domain,
            "context": {"default_project_id": self.project_id.id, "default_version_id": self.id},
        }

    def action_open_correction(self):
        self.ensure_one()
        self._ensure_manager()
        if not self.is_agile_release or self.state != "released":
            raise UserError(_("Corrections are available only for released Agile records."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Correct released record"),
            "res_model": "agile_community.release_correction_wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_release_id": self.id},
        }

    def _apply_release_correction(self, vals, reason):
        self.ensure_one()
        self._ensure_manager()
        if self.state != "released" or not reason or not reason.strip():
            raise ValidationError(_("A released record and a correction reason are required."))
        previous = self._audit_snapshot()
        super(ProjectVersion, self).write(vals)
        self._log_event(
            "corrected", reason=reason.strip(), previous_values=previous,
            new_values=self._audit_snapshot(),
        )
        return True

    def _apply_issue_correction(self, issue, target_version, reason, membership_action):
        self.ensure_one()
        self._ensure_manager()
        if self.state != "released" or not reason or not reason.strip():
            raise ValidationError(_("A released record and a correction reason are required."))
        if issue.project_id != self.project_id or not issue.agile_issue:
            raise ValidationError(_("Choose an Agile issue from the release's project."))
        if target_version and (
            target_version.project_id != self.project_id
            or not target_version.is_agile_release
            or not target_version.active
            or (target_version != self and target_version.state != "planned")
        ):
            raise ValidationError(_("Correct an issue only to this release or another planned release in the same project."))
        if membership_action == "add" and issue.version_id and issue.version_id != self:
            raise ValidationError(_("Remove the issue from its current planned release before adding it here."))
        if membership_action == "add" and issue.version_id == self:
            raise ValidationError(_("This issue is already included in the release."))
        if membership_action != "add" and issue.version_id != self:
            raise ValidationError(_("The selected issue's release target has changed; reload and try again."))
        previous = {
            "version_id": issue.version_id.id or False,
            "release": issue.version_id.display_name if issue.version_id else False,
        }
        issue._agile_apply_release_membership_correction(target_version.id if target_version else False)
        new = {
            "version_id": target_version.id if target_version else False,
            "release": target_version.display_name if target_version else False,
        }
        self._log_event(
            "corrected", reason=reason.strip(), previous_values=previous,
            new_values=new, issue=issue,
        )
        if target_version and target_version != self:
            target_version._log_event(
                "corrected", reason=reason.strip(), previous_values=previous,
                new_values=new, issue=issue,
            )
        return True


class ProjectTask(models.Model):
    _inherit = "project.task"

    @api.model_create_multi
    def create(self, vals_list):
        tasks = super().create(vals_list)
        tasks._check_agile_release_assignment()
        return tasks

    def write(self, vals):
        if "version_id" in vals:
            if self.sudo().filtered(lambda task: task.version_id.state == "released"):
                raise UserError(_("An issue in a released version can only be changed through its correction action."))
        result = super().write(vals)
        if "version_id" in vals or "project_id" in vals:
            self._check_agile_release_assignment()
        return result

    def _check_agile_release_assignment(self):
        for task in self.sudo().filtered("version_id"):
            release = task.version_id
            if release.project_id != task.project_id:
                raise ValidationError(_("An issue and its target release must belong to the same project."))
            if release.is_agile_release and not task.agile_issue:
                raise ValidationError(
                    _("Prepare this existing task as an Agile issue before assigning an Agile release.")
                )
            if task.agile_issue and release.state == "released":
                raise ValidationError(_("An issue cannot target a release that is already released."))
            if task.agile_issue and not release.active:
                raise ValidationError(_("An issue cannot target an archived release."))

    def _agile_apply_release_membership_correction(self, version_id):
        self.ensure_one()
        super(ProjectTask, self).write({"version_id": version_id})


class AgileReleaseAudit(models.Model):
    _name = "agile_community.release_audit"
    _description = "Agile Release History"
    _order = "event_date desc, id desc"

    release_id = fields.Many2one("project.version", required=True, ondelete="restrict", index=True)
    event_type = fields.Selection(
        [("created", "Created"), ("released", "Released"), ("corrected", "Corrected")],
        required=True,
    )
    actor_id = fields.Many2one("res.users", required=True, readonly=True)
    event_date = fields.Datetime(required=True, readonly=True)
    reason = fields.Text(readonly=True)
    previous_values = fields.Json(readonly=True)
    new_values = fields.Json(readonly=True)
    issue_id = fields.Many2one("project.task", readonly=True, ondelete="set null")

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise AccessError(_("Release history is written only by release actions."))
        return super().create(vals_list)

    def write(self, vals):
        if self.env.su:
            return super().write(vals)
        raise AccessError(_("Release history cannot be changed."))

    def unlink(self):
        if self.env.su:
            return super().unlink()
        raise AccessError(_("Release history cannot be deleted."))
