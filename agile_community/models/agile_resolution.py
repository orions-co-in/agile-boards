from odoo import _, api, fields, models
from odoo.exceptions import AccessError

RESOLUTIONS = [
    ("done", "Done"),
    ("wont_do", "Won't do"),
    ("duplicate", "Duplicate"),
    ("cannot_reproduce", "Cannot reproduce"),
]
DEFAULT_RESOLUTION = {"done": "done", "canceled": "wont_do"}


class ProjectProject(models.Model):
    _inherit = "project.project"

    agile_use_resolution = fields.Boolean(
        string="Ask for a resolution",
        copy=True,
        help="When on, completing or canceling an issue asks why it was closed: Done, Won't do, Duplicate or Cannot reproduce.",
    )

    def write(self, vals):
        if "agile_use_resolution" in vals and not self.env.su:
            for project in self:
                if project.agile_enabled and not self.env.user.has_group("base.group_system") and (
                    project._agile_role_for_user(self.env.user) != "manager"
                ):
                    raise AccessError(_("Only this project's Agile Manager can change the resolution setting."))
        return super().write(vals)


class ProjectTask(models.Model):
    _inherit = "project.task"

    agile_resolution = fields.Selection(
        RESOLUTIONS, string="Resolution", copy=False, index=True, tracking=True,
        help="Why the issue was closed. Set when it is completed or canceled; cleared when it is reopened.",
    )
    agile_uses_resolution = fields.Boolean(related="project_id.agile_use_resolution")

    def _agile_apply_resolution(self, transitions):
        """Give a closed issue its default resolution, and clear it when the issue is reopened."""
        for task, _source, target in transitions:
            if not task.agile_uses_resolution:
                continue
            closing = DEFAULT_RESOLUTION.get(target.agile_status)
            if closing and not task.agile_resolution:
                task.sudo().agile_resolution = closing
            elif not closing and task.agile_resolution:
                task.sudo().agile_resolution = False

    def action_agile_pick_resolution(self):
        """Complete or Cancel Issue on a project that asks for a resolution: a small dialog first."""
        self.ensure_one()
        kind = self.env.context.get("agile_close", "done")
        return {
            "type": "ir.actions.act_window",
            "name": _("Cancel this issue") if kind == "canceled" else _("Complete this issue"),
            "res_model": "agile_community.resolution_wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_task_id": self.id, "default_kind": kind},
        }
