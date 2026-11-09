import math

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare


class ProjectSprintCapacity(models.Model):
    _name = "project.sprint.capacity"
    _description = "Project Sprint Member Capacity"
    _order = "sprint_id, user_id"

    _sprint_user_unique = models.Constraint(
        "UNIQUE(sprint_id, user_id)",
        "Each sprint member can have only one capacity entry.",
    )
    _capacity_nonnegative = models.Constraint(
        "CHECK (capacity_points >= 0)",
        "Sprint capacity cannot be negative.",
    )

    sprint_id = fields.Many2one(
        "project.sprint", required=True, ondelete="cascade", index=True
    )
    user_id = fields.Many2one(
        "res.users",
        required=True,
        ondelete="restrict",
        domain="[('share', '=', False), ('id', 'in', sprint_member_ids)]",
    )
    sprint_member_ids = fields.Many2many(
        related="sprint_id.user_ids", string="Sprint Members"
    )
    capacity_points = fields.Float(
        string="Capacity (points)", required=True, default=0.0, digits=(16, 2)
    )
    planned_points = fields.Float(
        string="Planned (points)", compute="_compute_planned_points"
    )
    over_capacity = fields.Boolean(compute="_compute_planned_points")
    can_manage_project_capacity = fields.Boolean(
        related="sprint_id.can_manage_project_sprint"
    )

    def _check_project_manager_role(self, sprint):
        if not sprint:
            raise UserError(self.env._("Choose a sprint before setting capacity."))
        sprint._check_project_manager_role()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._validate_capacity_input(vals)
            sprint = self.env["project.sprint"].browse(vals.get("sprint_id"))
            self._check_project_manager_role(sprint)
            self._check_editable_sprint(sprint)
        return super().create(vals_list)

    def write(self, vals):
        self._validate_capacity_input(vals)
        for line in self:
            self._check_project_manager_role(line.sprint_id)
            target_sprint = (
                self.env["project.sprint"].browse(vals["sprint_id"])
                if "sprint_id" in vals
                else line.sprint_id
            )
            self._check_project_manager_role(target_sprint)
            self._check_editable_sprint(
                target_sprint
            )
        return super().write(vals)

    @api.model
    def _validate_capacity_input(self, vals):
        if "capacity_points" not in vals:
            return
        try:
            capacity = float(vals["capacity_points"])
        except (TypeError, ValueError):
            capacity = math.nan
        if not math.isfinite(capacity) or capacity < 0:
            raise ValidationError(
                self.env._("Sprint capacity must be a finite, nonnegative number.")
            )

    def unlink(self):
        for line in self:
            self._check_project_manager_role(line.sprint_id)
            self._check_editable_sprint(line.sprint_id)
        return super().unlink()

    @api.model
    def _check_editable_sprint(self, sprint):
        if not sprint or sprint.state != "draft":
            raise UserError(
                self.env._("Member capacity can only be edited while the sprint is planned.")
            )

    @api.constrains("sprint_id", "user_id", "capacity_points")
    def _check_capacity_values(self):
        for line in self:
            if (
                not math.isfinite(line.capacity_points)
                or line.capacity_points < 0
            ):
                raise ValidationError(
                    self.env._("Sprint capacity must be a finite, nonnegative number.")
                )
            if line.user_id not in line.sprint_id.user_ids:
                raise ValidationError(
                    self.env._("Choose a member of this sprint.")
                )

    @api.depends(
        "sprint_id.task_ids.story_points",
        "sprint_id.task_ids.story_points_estimated",
        "sprint_id.project_id.scrum_estimate_unit",
        "sprint_id.task_ids.state",
        "sprint_id.task_ids.user_ids",
        "sprint_id.task_ids.child_ids",
        "sprint_id.commitment_ids.line_ids.story_points_snapshot",
        "sprint_id.commitment_ids.line_ids.user_ids",
        "user_id.active",
    )
    def _compute_planned_points(self):
        for line in self:
            if not line.user_id.active:
                line.planned_points = 0.0
                line.over_capacity = False
                continue
            line.planned_points = sum(
                entry["points"] / len(entry["users"])
                for entry in line.sprint_id._get_point_entries()
                if entry["estimated"] and line.user_id in entry["users"]
            )
            line.over_capacity = (
                float_compare(
                    line.planned_points,
                    line.capacity_points,
                    precision_digits=2,
                )
                > 0
            )
