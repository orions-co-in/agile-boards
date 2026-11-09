from datetime import timedelta

import pytz
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError


class ProjectSprint(models.Model):
    _inherit = "project.sprint"

    def _agile_run_automation(self, trigger):
        """Hook: agile_pro runs the project's sprint rules."""

    retro_notes = fields.Text(
        string="Retrospective notes",
        copy=False,
        tracking=True,
        help="What went well, what to change, and what to try next sprint.",
    )

    reopen_count = fields.Integer(readonly=True, copy=False)
    can_reopen_sprint = fields.Boolean(compute="_compute_can_reopen_sprint")

    @api.depends_context("uid")
    @api.depends("state", "project_id", "date_start", "project_id.sprint_ids.state")
    def _compute_can_reopen_sprint(self):
        for sprint in self:
            sprint.can_reopen_sprint = not sprint._agile_reopen_blocker()

    def _agile_reopen_blocker(self):
        """Why this sprint cannot be reopened now; an empty text when it can (R-1106)."""
        self.ensure_one()
        project = self.project_id
        if self.state != "done":
            return _("Only a completed sprint can be reopened.")
        if not project.agile_enabled or project._agile_role_for_user() != "manager":
            return _("Only project managers can reopen a sprint.")
        sprints = self.sudo().search([("project_id", "=", project.id), ("id", "!=", self.id)])
        if sprints.filtered(
            lambda other: other.state != "draft"
            and (other.date_start, other.id) > (self.date_start, self.id)
        ):
            return _("A later sprint has started, so this sprint can no longer be reopened.")
        if not project.allow_multiple_active_sprints and sprints.filtered(lambda other: other.state == "in_progress"):
            return _("Another sprint is active. Complete it first.")
        return ""

    def agile_reopen(self, reason):
        """A manager makes a completed sprint active again; the committed plan is not touched."""
        self.ensure_one()
        self._check_project_manager_role()
        blocker = self._agile_reopen_blocker()
        if blocker:
            raise UserError(blocker)
        reason = (reason or "").strip()
        if len(reason) < 5:
            raise ValidationError(_("Write why you are reopening it (at least 5 characters)."))
        self.with_context(agile_reopen_sprint=True).write({"state": "in_progress"})
        # The closing totals are system managed and counted again when the sprint is completed again,
        # so they are cleared here, below the checked write (the summary is a translated field).
        self.flush_recordset()
        self.env.cr.execute(
            """
            UPDATE project_sprint
               SET close_summary = NULL, completed_task_count = 0, completed_points = 0,
                   committed_points_at_close = 0, reopen_count = COALESCE(reopen_count, 0) + 1
             WHERE id = %s
            """,
            (self.id,),
        )
        self.invalidate_recordset()
        self.message_post(body=_("Sprint reopened by %(user)s. Reason: %(reason)s", user=self.env.user.name, reason=reason))
        self.project_id._agile_audit("sprints", _("Sprint %(name)s reopened. Reason: %(reason)s", name=self.name, reason=reason))
        return True

    def action_agile_open_reopen(self):
        """Open the reason dialog for reopening this sprint."""
        self.ensure_one()
        self._check_project_manager_role()
        blocker = self._agile_reopen_blocker()
        if blocker:
            raise UserError(blocker)
        return {
            "type": "ir.actions.act_window",
            "name": _("Reopen sprint"),
            "res_model": "agile.sprint.reopen",
            "view_mode": "form",
            "target": "new",
            "context": {"default_sprint_id": self.id},
        }

    def agile_retro_add_action(self, name):
        """Create a Backlog issue from a retrospective and link it to this sprint."""
        self.ensure_one()
        self._check_project_manager_role()
        name = (name or "").strip()
        if not name:
            raise UserError(_("Write what the team will do."))
        if self.state == "draft":
            raise UserError(_("Retrospective actions can be added once the sprint has started."))
        task = self.env["project.task"].create({
            "name": name,
            "project_id": self.project_id.id,
            "retro_sprint_id": self.id,
        })
        return {"id": task.id, "key": task.issue_key or "", "name": task.name}

    def agile_retro_actions(self):
        """The actions of this sprint's retrospective that the user may read."""
        self.ensure_one()
        tasks = self.env["project.task"].search(
            [("retro_sprint_id", "=", self.id)], order="id"
        )
        return [
            {"id": t.id, "key": t.issue_key or "", "name": t.name,
             "status": t.stage_id.name or "",
             "open": t.stage_id.agile_status not in ("done", "canceled")}
            for t in tasks
        ]

    def agile_open_retro_actions(self):
        """Open actions from the sprint before this one, for its planning and review."""
        self.ensure_one()
        previous = self.search(
            [("project_id", "=", self.project_id.id), ("state", "!=", "draft"),
             ("date_start", "<", self.date_start)],
            order="date_start desc, id desc", limit=1,
        )
        if not previous:
            return {"sprint": False, "actions": []}
        rows = [row for row in previous.agile_retro_actions() if row["open"]]
        return {"sprint": {"id": previous.id, "name": previous.name}, "actions": rows}

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        project_id = values.get("project_id") or self.env.context.get("default_project_id")
        if "date_start" in fields_list and project_id:
            project = self.env["project.project"].browse(project_id).exists()
            if project and project.agile_enabled:
                utc_now = fields.Datetime.now()
                if not utc_now.tzinfo:
                    utc_now = pytz.UTC.localize(utc_now)
                timezone = pytz.timezone(project.agile_timezone or "UTC")
                today = utc_now.astimezone(timezone).date()
                # A new sprint follows the project's latest one instead of overlapping it (NU-04).
                latest = self.search(
                    [("project_id", "=", project.id)], order="date_end desc, id desc", limit=1
                )
                if latest and latest.date_end:
                    today = max(today, latest.date_end + timedelta(days=1))
                values["date_start"] = today
        return values

    def action_agile_open_start(self):
        """Open the Start sprint dialog: name, dates, goal and warnings (NU-05)."""
        self.ensure_one()
        self._check_project_manager_role()
        if not self.planning_confirmed:
            raise UserError(_("Confirm the sprint plan before starting it."))
        wizard = self.env["agile.sprint.start.wizard"].create({
            "sprint_id": self.id,
            "name": self.name,
            "date_start": self.date_start,
            "date_end": self.date_end,
            "goal": self.description,
        })
        return {
            "type": "ir.actions.act_window",
            "name": _("Start sprint"),
            "res_model": "agile.sprint.start.wizard",
            "res_id": wizard.id,
            "view_mode": "form",
            "target": "new",
        }

    def _agile_align_date_option(self, vals):
        """An explicit end date that disagrees with the chosen length makes it a custom sprint."""
        if "date_end" not in vals:
            return
        option = vals.get("date_option") or (self.date_option if self else None)
        start = vals.get("date_start") or (self.date_start if self else None)
        if not option or option == "custom" or not start or not vals["date_end"]:
            return
        number, unit = option.split("_")
        expected = fields.Date.to_date(start) + relativedelta(**{unit: int(number)})
        if fields.Date.to_date(vals["date_end"]) != expected:
            vals["date_option"] = "custom"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("date_end") and vals.get("date_option", "1_weeks") != "custom":
                # Core leaves the end date empty (a database error) when only the length is given.
                # The project may come from the quick-create context only (NU-31), so default_get reads it too.
                project_id = vals.get("project_id") or self.env.context.get("default_project_id")
                start = vals.get("date_start") or self.with_context(
                    default_project_id=project_id
                ).default_get(["date_start"]).get("date_start")
                option = vals.get("date_option", "1_weeks")
                number, unit = option.split("_")
                vals["date_end"] = fields.Date.to_date(start) + relativedelta(**{unit: int(number)})
            self._agile_align_date_option(vals)
        return super().create(vals_list)

    def write(self, vals):
        if "retro_notes" in vals and any(sprint.state == "draft" for sprint in self):
            raise UserError(
                _("Retrospective notes can be written once the sprint has started.")
            )
        changing = self.browse()
        if vals.get("state") in ("in_progress", "done"):
            changing = self.filtered(lambda sprint: sprint.state != vals["state"])
        if "date_end" not in vals:
            result = super().write(vals)
        else:
            for sprint in self:
                sprint_vals = dict(vals)
                sprint._agile_align_date_option(sprint_vals)
                super(ProjectSprint, sprint).write(sprint_vals)
            result = True
        if changing:
            trigger = "sprint_start" if vals["state"] == "in_progress" else "sprint_end"
            changing._agile_run_automation(trigger)
        return result

    def action_tasks(self):
        self.check_access("read")
        action = super().action_tasks()
        if self.project_id.agile_enabled:
            action["domain"] = list(action.get("domain") or []) + [
                ("agile_issue", "=", True)
            ]
            action["search_view_id"] = self.env.ref(
                "agile_community.project_task_search_agile"
            ).id
            action["views"] = [
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
            ]
            context = action.setdefault("context", {})
            context["agile_project_view"] = True
            context["subtask_action"] = True
            action = self.project_id._agile_apply_view_preference(action)
        return action

    @api.depends_context("uid")
    @api.depends(
        "project_id",
        "project_id.agile_enabled",
        "project_id.agile_member_ids.user_id",
        "project_id.agile_member_ids.role",
    )
    def _compute_can_manage_project_sprint(self):
        for sprint in self:
            if not sprint.project_id and not sprint._origin.id:
                # A new sprint has no project yet; keep the form editable so one can
                # be chosen. The role is enforced for the chosen project on save.
                sprint.can_manage_project_sprint = self.env.user.has_group(
                    "project.group_project_user"
                )
                continue
            sprint.can_manage_project_sprint = sprint._is_project_manager_for_project(
                sprint.project_id
            )

    def _is_project_manager_for_project(self, project):
        if not project:
            return False
        if project.agile_enabled:
            return (
                project.with_user(self.env.user).has_access("read")
                and project._agile_role_for_user(self.env.user) == "manager"
            )
        return super()._is_project_manager_for_project(project)

    def _check_project_manager_role(self, project=False):
        projects = self.mapped("project_id") if self else project
        for project_record in projects:
            if (
                project_record.agile_enabled
                and not project_record.with_user(self.env.user).has_access("read")
            ):
                raise AccessError(
                    _("You must retain native Odoo Project access to manage this sprint.")
                )
        return super()._check_project_manager_role(project=project)


class ProjectTask(models.Model):
    _inherit = "project.task"

    def _check_task_sprint_membership_permission(self, project):
        if project.agile_enabled and not project._agile_allows("sprint_membership"):
            raise AccessError(
                _("Only this project's Agile Manager can change sprint membership.")
            )
        if project.agile_enabled and any(not task.agile_issue for task in self):
            raise AccessError(
                _("Prepare existing tasks as Agile issues before adding them to a sprint.")
            )
        return super()._check_task_sprint_membership_permission(project)
