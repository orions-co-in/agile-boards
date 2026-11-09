from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class ProjectSprintCorrection(models.Model):
    _name = "project.sprint.correction"
    _description = "Project Sprint Administrative Correction"
    _order = "create_date desc, id desc"

    sprint_id = fields.Many2one(
        "project.sprint", required=True, ondelete="restrict", index=True
    )
    task_id = fields.Many2one("project.task", ondelete="set null", index=True)
    issue_key = fields.Char(required=True, readonly=True)
    task_name = fields.Char(required=True, readonly=True)
    operation = fields.Selection(
        [("add", "Added to completed sprint"), ("remove", "Returned to backlog")],
        required=True,
        readonly=True,
    )
    reason = fields.Text(required=True, readonly=True)
    user_id = fields.Many2one(
        "res.users", required=True, readonly=True, ondelete="restrict"
    )
    state = fields.Selection(
        [("pending", "Pending"), ("applying", "Applying"), ("applied", "Applied")],
        required=True,
        default="pending",
        readonly=True,
    )
    create_date = fields.Datetime(readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("allow_sprint_correction_write"):
            raise UserError(self.env._("Sprint corrections are system managed."))
        return super().create(vals_list)

    def write(self, vals):
        if (
            not self.env.context.get("allow_sprint_correction_write")
            or set(vals) != {"state"}
        ):
            raise UserError(self.env._("Sprint correction history cannot be edited."))
        allowed = {"pending": "applying", "applying": "applied"}
        for correction in self:
            if allowed.get(correction.state) != vals["state"]:
                raise UserError(self.env._("Invalid correction history transition."))
        return super().write(vals)

    def unlink(self):
        if self.env.context.get("module_uninstall"):
            return super().unlink()
        raise UserError(self.env._("Sprint correction history cannot be deleted."))


class ProjectSprintCorrectionWizard(models.TransientModel):
    _name = "project.sprint.correction.wizard"
    _description = "Correct Completed Sprint Membership"

    sprint_id = fields.Many2one(
        "project.sprint", required=True, readonly=True, ondelete="cascade"
    )
    project_id = fields.Many2one(related="sprint_id.project_id", readonly=True)
    operation = fields.Selection(
        [("add", "Add issue to completed sprint"), ("remove", "Return issue to backlog")],
        required=True,
        default="add",
    )
    task_ids = fields.Many2many(
        "project.task",
        string="Issues",
        domain="[('project_id', '=', project_id)]",
        required=True,
    )
    reason = fields.Text(required=True)

    def action_apply(self):
        self.ensure_one()
        sprint = self.sprint_id
        sprint._check_project_manager_role()
        if sprint.state != "done":
            raise UserError(
                self.env._("Corrections are available only for completed sprints.")
            )
        reason = (self.reason or "").strip()
        if not reason:
            raise ValidationError(self.env._("Enter a reason for this correction."))
        if not self.task_ids:
            raise ValidationError(self.env._("Select at least one issue to correct."))

        correction_model = self.env["project.sprint.correction"].sudo().with_context(
            allow_sprint_correction_write=True
        )
        for task in self.task_ids:
            if task.project_id != sprint.project_id:
                raise ValidationError(
                    self.env._("Every issue must belong to the sprint project.")
                )
            if self.operation == "add":
                if task.sprint_id:
                    raise ValidationError(
                        self.env._(
                            "Return an issue to the backlog before adding it to a completed sprint."
                        )
                    )
            elif task.sprint_id != sprint:
                raise ValidationError(
                    self.env._("Only issues in this sprint can be returned to backlog.")
                )
            correction = correction_model.create(
                {
                    "sprint_id": sprint.id,
                    "task_id": task.id,
                    "issue_key": getattr(task, "issue_key", False) or task.display_name,
                    "task_name": task.name,
                    "operation": self.operation,
                    "reason": reason,
                    "user_id": self.env.uid,
                }
            )
            correction.with_context(allow_sprint_correction_write=True).write(
                {"state": "applying"}
            )
            task.with_context(sprint_correction_id=correction.id).write(
                {"sprint_id": sprint.id if self.operation == "add" else False}
            )
            correction.with_context(allow_sprint_correction_write=True).write(
                {"state": "applied"}
            )
        sprint.message_post(
            body=self.env._(
                "%(count)s issue(s) corrected by %(user)s. Reason: %(reason)s",
                count=len(self.task_ids),
                user=self.env.user.name,
                reason=reason,
            )
        )
        return {"type": "ir.actions.act_window_close"}
