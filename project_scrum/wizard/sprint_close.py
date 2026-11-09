from odoo import api, fields, models
from odoo.exceptions import UserError


class ProjectSprintClose(models.TransientModel):
    _name = "project.sprint.close"
    _description = "Complete Project Sprint"

    sprint_id = fields.Many2one("project.sprint", required=True, readonly=True)
    name = fields.Char(related="sprint_id.name", readonly=True)
    # The sprint stores its completed count only when it closes, so count the Done issues now.
    done_count = fields.Integer(
        string="Completed Issues", compute="_compute_done_count", readonly=True
    )
    committed_count = fields.Integer(
        related="sprint_id.committed_task_count", readonly=True
    )
    unfinished_task_ids = fields.Many2many(
        "project.task", compute="_compute_unfinished_tasks", readonly=True
    )
    disposition = fields.Selection(
        [("backlog", "Return to backlog"), ("sprint", "Another planned sprint")],
        required=True,
        default="backlog",
    )
    destination_sprint_id = fields.Many2one(
        "project.sprint",
        string="Move unfinished issues to",
        domain="[('project_id', '=', project_id), ('state', '=', 'draft')]",
    )
    project_id = fields.Many2one(related="sprint_id.project_id", readonly=True)

    @api.depends("sprint_id.task_ids.state")
    def _compute_done_count(self):
        for wizard in self:
            wizard.done_count = len(
                wizard.sprint_id.task_ids.filtered(lambda task: task.state == "1_done")
            )

    def _compute_unfinished_tasks(self):
        for wizard in self:
            wizard.unfinished_task_ids = wizard.sprint_id.task_ids.filtered(
                lambda task: task.state not in ("1_done", "1_canceled")
            )

    def action_complete(self):
        self.ensure_one()
        sprint = self.sprint_id
        sprint._check_project_manager_role()
        unfinished = self.unfinished_task_ids
        if unfinished and self.disposition == "sprint" and not self.destination_sprint_id:
            raise UserError(
                self.env._("Choose the planned sprint for unfinished issues.")
            )
        if self.disposition == "sprint" and self.destination_sprint_id:
            if self.destination_sprint_id.project_id != sprint.project_id:
                raise UserError(self.env._("Choose a planned sprint in the same project."))
            if self.destination_sprint_id.state != "draft":
                raise UserError(self.env._("The destination sprint must still be planned."))
            unfinished.write({"sprint_id": self.destination_sprint_id.id})
        elif self.disposition == "backlog":
            unfinished.write({"sprint_id": False})
        sprint.action_done()
        return {"type": "ir.actions.act_window_close"}
