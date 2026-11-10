import math

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

MAX_STORY_POINTS = 10000  # E2E-004: an estimate is a small relative number; 1e30 was stored

class ProjectTask(models.Model):
    _inherit = "project.task"

    story_points = fields.Float(
        string="Story Points",
        digits=(16, 2),
        default=0.0,
        tracking=True,
        copy=True,
        help=(
            "Optional relative story-point estimate, not hours. Zero is a real estimate; "
            "clear Estimated to make the issue unestimated. Confirmed sprint reports "
            "continue to use their saved commitment snapshot."
        ),
    )
    story_points_estimated = fields.Boolean(
        string="Estimated",
        default=False,
        tracking=True,
        copy=True,
    )
    sprint_group_points = fields.Float(
        string="Sprint Points",
        compute="_compute_sprint_group_totals",
        store=True,
        aggregator="sum",
        digits=(16, 2),
    )
    sprint_group_unestimated_count = fields.Integer(
        string="Unestimated Issues",
        compute="_compute_sprint_group_totals",
        store=True,
        aggregator="sum",
    )

    sprint_id = fields.Many2one(
        comodel_name="project.sprint",
        string="Sprint",
        tracking=True,
        domain="[('state', '!=', 'done'), ('project_id', '=', project_id)]",
    )

    sprint_state = fields.Selection(
        related="sprint_id.state", string="Sprint State", store=True
    )

    _story_points_nonnegative = models.Constraint(
        "CHECK (story_points >= 0)", "Story points cannot be negative."
    )

    @api.depends(
        "sprint_id",
        "state",
        "story_points",
        "story_points_estimated",
        "project_id.scrum_estimate_unit",
        "child_ids.sprint_id",
    )
    def _compute_sprint_group_totals(self):
        for task in self:
            is_counted = bool(
                task.sprint_id
                and task.state != "1_canceled"
                and not (task.child_ids & task.sprint_id.task_ids)
            )
            estimated, points = task._scrum_estimate()
            task.sprint_group_points = points if is_counted and estimated else 0.0
            task.sprint_group_unestimated_count = int(is_counted and not estimated)

    def _scrum_estimate(self):
        """(estimated, value) as the project counts it: Issue count makes every issue worth 1."""
        self.ensure_one()
        if self.project_id.scrum_estimate_unit == "issues":
            return True, 1.0
        return self.story_points_estimated, self.story_points

    @api.model_create_multi
    def create(self, vals_list):
        normalized_vals = []
        for vals in vals_list:
            vals = dict(vals)
            sprint = self.env["project.sprint"].browse(vals.get("sprint_id"))
            if sprint:
                self._check_task_sprint_membership_permission(sprint.project_id)
            if sprint.state == "done":
                raise UserError(
                    self.env._(
                        "A completed sprint cannot accept issues outside the audited correction action."
                    )
                )
            if "story_points" in vals and "story_points_estimated" not in vals:
                vals["story_points_estimated"] = True
            if not vals.get("story_points_estimated"):
                vals["story_points"] = 0.0
            normalized_vals.append(vals)
        return super().create(normalized_vals)

    def write(self, vals):
        vals = dict(vals)
        if "story_points" in vals and "story_points_estimated" not in vals:
            vals["story_points_estimated"] = True
        if vals.get("story_points_estimated") is False:
            vals["story_points"] = 0.0

        if "sprint_id" in vals:
            target_sprint_id = vals["sprint_id"] or False
            target_sprint = self.env["project.sprint"].browse(target_sprint_id)
            for task in self:
                old_sprint = task.sprint_id
                if old_sprint:
                    task._check_task_sprint_membership_permission(old_sprint.project_id)
                task._check_task_sprint_membership_permission(task.project_id)
                if target_sprint:
                    task._check_task_sprint_membership_permission(
                        target_sprint.project_id
                    )
                if (old_sprint.state == "done" or target_sprint.state == "done") and not self._has_valid_sprint_correction(
                    task, old_sprint, target_sprint
                ):
                    raise UserError(
                        self.env._(
                            "Completed sprint membership can only change through the audited correction action."
                        )
                    )
        return super().write(vals)

    def _check_task_sprint_membership_permission(self, project):
        """Extension point; native Scrum keeps its OCA membership behavior."""
        return True

    def _has_valid_sprint_correction(self, task, old_sprint, target_sprint):
        correction_id = self.env.context.get("sprint_correction_id")
        if not correction_id:
            return False
        correction = self.env["project.sprint.correction"].sudo().browse(
            correction_id
        )
        if not correction.exists():
            return False
        try:
            correction.sprint_id._check_project_manager_role()
        except UserError:
            return False
        return bool(
            correction.state == "applying"
            and correction.task_id == task
            and correction.sprint_id
            and correction.sprint_id.project_id == task.project_id
            and (
                (
                    correction.operation == "add"
                    and target_sprint == correction.sprint_id
                    and old_sprint != correction.sprint_id
                    and not old_sprint
                )
                or (
                    correction.operation == "remove"
                    and old_sprint == correction.sprint_id
                    and not target_sprint
                )
            )
        )

    @api.constrains("story_points", "story_points_estimated")
    def _check_story_points(self):
        for task in self:
            if not math.isfinite(task.story_points) or task.story_points < 0:
                raise ValidationError(
                    self.env._("Story points must be a finite, nonnegative number.")
                )
            if task.story_points > MAX_STORY_POINTS:
                raise ValidationError(
                    self.env._(
                        "Story points cannot be more than %(max)s.", max=f"{MAX_STORY_POINTS:,}"
                    )
                )
            if not task.story_points_estimated and task.story_points:
                raise ValidationError(
                    self.env._("Clear the estimate flag before removing story points.")
                )

    @api.constrains("project_id", "sprint_id")
    def _check_sprint_project(self):
        for task in self:
            if task.sprint_id and (
                not task.project_id
                or task.sprint_id.project_id != task.project_id
                or not task.project_id.use_scrum
            ):
                raise ValidationError(
                    self.env._("Choose a sprint from this Scrum-enabled project.")
                )
            if task.sprint_id.state == "done" and not self.env.context.get(
                "sprint_correction_id"
            ):
                raise ValidationError(
                    self.env._(
                        "A completed sprint cannot accept issues outside the audited correction action."
                    )
                )
