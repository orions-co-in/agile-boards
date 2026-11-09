from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError


class AgileReleaseCorrectionWizard(models.TransientModel):
    _name = "agile_community.release_correction_wizard"
    _description = "Correct a Released Agile Record"

    release_id = fields.Many2one("project.version", required=True, readonly=True)
    project_id = fields.Many2one(related="release_id.project_id", readonly=True)
    correction_type = fields.Selection(
        [("details", "Release details"), ("issue", "Issue membership")],
        required=True,
        default="details",
    )
    reason = fields.Text(required=True)
    name = fields.Char(string="Release name")
    release_date = fields.Date(string="Target date")
    description = fields.Text()
    milestone_id = fields.Many2one(
        "project.milestone", domain="[('project_id', '=', project_id)]"
    )
    clear_target_date = fields.Boolean()
    clear_description = fields.Boolean()
    clear_milestone = fields.Boolean()
    issue_id = fields.Many2one(
        "project.task",
        string="Issue to correct",
        domain="[('project_id', '=', project_id), ('agile_issue', '=', True)]",
    )
    membership_action = fields.Selection(
        [
            ("add", "Add to this release"),
            ("remove", "Remove from this release"),
            ("move", "Move to another planned release"),
        ],
        default="remove",
        required=True,
    )
    target_version_id = fields.Many2one(
        "project.version",
        string="Target planned release",
        domain="[('project_id', '=', project_id), ('state', '=', 'planned'), ('active', '=', True)]",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            release = self.env["project.version"].browse(
                vals.get("release_id") or self.env.context.get("default_release_id")
            )
            release._ensure_manager()
        return super().create(vals_list)

    def action_apply(self):
        self.ensure_one()
        self.release_id._ensure_manager()
        if not self.reason or not self.reason.strip():
            raise ValidationError(_("Enter a reason for this correction."))
        release = self.release_id
        if release.state != "released" or not release.is_agile_release:
            raise UserError(_("This correction is no longer available."))
        if self.correction_type == "details":
            vals = {}
            if self.name:
                vals["name"] = self.name.strip()
            if self.release_date:
                vals["release_date"] = self.release_date
            elif self.clear_target_date:
                vals["release_date"] = False
            if self.description:
                vals["description"] = self.description
            elif self.clear_description:
                vals["description"] = False
            if self.milestone_id:
                vals["milestone_id"] = self.milestone_id.id
            elif self.clear_milestone:
                vals["milestone_id"] = False
            if not vals:
                raise ValidationError(_("Choose at least one release detail to correct."))
            release._apply_release_correction(vals, self.reason)
        else:
            if not self.issue_id:
                raise ValidationError(_("Choose the issue whose release target needs correction."))
            target = release if self.membership_action == "add" else False
            if self.membership_action == "move":
                if not self.target_version_id:
                    raise ValidationError(_("Choose the planned release to receive this issue."))
                target = self.target_version_id
            release._apply_issue_correction(
                self.issue_id, target, self.reason, self.membership_action
            )
        return {"type": "ir.actions.act_window_close"}
