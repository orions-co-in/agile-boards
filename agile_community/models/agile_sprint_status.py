from odoo import _, api, models
from odoo.exceptions import AccessError, UserError, ValidationError


class ProjectTask(models.Model):
    _inherit = "project.task"

    @api.model_create_multi
    def create(self, vals_list):
        tasks = super().create(vals_list)
        tasks.filtered(
            lambda task: task.sprint_id and task.agile_status == "backlog"
        )._agile_follow_sprint("ready")
        return tasks

    def write(self, vals):
        """Moving an issue into a sprint makes it To Do; moving it out sends it back (B-403)."""
        follow = "sprint_id" in vals and not self.env.context.get("agile_keep_status")
        leaving = self.browse()
        if follow and not vals["sprint_id"]:
            leaving = self.filtered(lambda task: task.sprint_id and task.agile_status == "ready")
        result = super().write(vals)
        if follow:
            if vals["sprint_id"]:
                self.filtered(lambda task: task.agile_status == "backlog")._agile_follow_sprint("ready")
            leaving._agile_follow_sprint("backlog")
        return result

    def _agile_follow_sprint(self, target_status):
        """Move Agile issues (not epics) to the status that matches their sprint.

        The sprint change was already authorised, so the move skips the workflow's
        transition rules (there is no Ready to Backlog transition, for one). When no
        stage can take it the reason goes on the issue and the sprint change stands.
        """
        stages = self.env["project.task.type"].sudo().with_context(active_test=False)
        for task in self.filtered(lambda t: t.agile_issue and not t.agile_is_epic):
            stage = stages.search([
                ("project_ids", "=", task.project_id.id),
                ("agile_status", "=", target_status),
            ], limit=1)
            try:
                if not stage or not stage.active:
                    raise UserError(_("The %s stage is missing or archived.", target_status))
                with self.env.cr.savepoint():
                    task.sudo()._write_agile_values({"stage_id": stage.id})
            except (AccessError, UserError, ValidationError) as error:
                task.message_post(
                    body=_(
                        "The sprint changed but the status stayed %(status)s: %(reason)s",
                        status=task.stage_id.name,
                        reason=error.args[0] if error.args else "",
                    )
                )
