from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AgileReleaseConfirmWizard(models.TransientModel):
    """Mark as Released: say how many issues are still open and offer to move them (NU-12)."""

    _name = "agile.release.confirm"
    _description = "Release with open issues"

    release_id = fields.Many2one("project.version", required=True, readonly=True, ondelete="cascade")
    open_count = fields.Integer(compute="_compute_open", readonly=True)
    open_list = fields.Text(compute="_compute_open", readonly=True)
    handling = fields.Selection(
        [("leave", "Leave them in this release"), ("move", "Move them to another version")],
        default="leave", required=True,
    )
    target_version_id = fields.Many2one(
        "project.version", string="Move to",
        domain="[('project_id', '=', project_id), ('id', '!=', release_id), ('state', '=', 'planned'), ('is_agile_release', '=', True)]",
    )
    project_id = fields.Many2one(related="release_id.project_id")

    @api.depends("release_id")
    def _compute_open(self):
        for wizard in self:
            tasks = wizard._open_issues()
            wizard.open_count = len(tasks)
            shown = tasks[:10].mapped(lambda task: f"{task.issue_key or ''} {task.name}".strip())
            more = len(tasks) - len(shown)
            wizard.open_list = "\n".join(shown + ([_("and %(count)s more", count=more)] if more > 0 else [])) or False

    def _open_issues(self):
        self.ensure_one()
        return self.env["project.task"].search([
            ("version_id", "=", self.release_id.id),
            ("project_id.agile_enabled", "=", True),
            ("agile_issue", "=", True),
            ("agile_is_epic", "=", False),
            ("stage_id.agile_status", "not in", ["done", "canceled"]),
        ])

    def action_confirm(self):
        self.ensure_one()
        release = self.release_id
        if self.open_count and self.handling == "move":
            if not self.target_version_id:
                raise UserError(_("Choose the version the open issues move to."))
            self._open_issues().write({"version_id": self.target_version_id.id})
        action = release.action_release()
        if action.get("params") is not None:
            action["params"]["next"] = {"type": "ir.actions.act_window_close"}
        return action
