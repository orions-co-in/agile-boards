from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


class AgileProjectWipLimit(models.Model):
    _name = "agile.project.wip.limit"
    _description = "Agile Project Stage WIP Limit"
    _order = "project_id, stage_id"

    project_id = fields.Many2one(
        "project.project", required=True, index=True, ondelete="cascade"
    )
    stage_id = fields.Many2one(
        "project.task.type",
        string="Workflow stage",
        required=True,
        index=True,
        ondelete="restrict",
        domain="[('project_ids', 'in', project_id), ('agile_status', 'in', ['backlog', 'ready', 'progress', 'review'])]",
    )
    wip_limit = fields.Integer(
        string="WIP limit",
        required=True,
        default=1,
        help="A soft planning guide. Reaching this number does not block issue movement.",
    )

    per_swimlane = fields.Boolean(
        string="Per swimlane row",
        help="Count the limit inside each swimlane row instead of across the whole column. "
        "Without swimlanes on the board the limit counts the whole column.",
    )

    _project_stage_unique = models.Constraint(
        "unique (project_id, stage_id)",
        "Set one WIP limit per workflow stage in a project.",
    )
    _positive_limit = models.Constraint(
        "CHECK (wip_limit > 0)", "A WIP limit must be greater than zero."
    )

    @api.constrains("project_id", "stage_id")
    def _check_stage_scope(self):
        for limit in self:
            if not limit.project_id.agile_enabled:
                raise ValidationError(
                    _("WIP limits can only be set on an Agile project.")
                )
            if (
                limit.project_id not in limit.stage_id.project_ids
                or limit.stage_id.agile_status not in ("backlog", "ready", "progress", "review")
            ):
                raise ValidationError(
                    _("Choose an active workflow stage in this project.")
                )

    @api.constrains("wip_limit")
    def _check_positive_limit(self):
        if any(limit.wip_limit <= 0 for limit in self):
            raise ValidationError(_("A WIP limit must be greater than zero."))

    @api.model_create_multi
    def create(self, vals_list):
        projects = self.env["project.project"].browse(
            [vals.get("project_id") for vals in vals_list]
        ).exists()
        self._check_project_managers(projects)
        limits = super().create(vals_list)
        for project in limits.project_id:
            project._agile_post_audit_note(
                _("A workflow stage WIP limit was added."),
                area="workflows",
            )
        return limits

    def write(self, vals):
        if "project_id" in vals:
            raise ValidationError(
                _("A WIP limit cannot be moved to another project. Remove it and add it to the other project instead.")
            )
        self._check_project_managers(self.project_id)
        result = super().write(vals)
        for project in self.project_id:
            project._agile_post_audit_note(
                _("Workflow stage WIP limits were updated."),
                area="workflows",
            )
        return result

    def unlink(self):
        projects = self.project_id
        self._check_project_managers(projects)
        result = super().unlink()
        for project in projects:
            project._agile_post_audit_note(
                _("A workflow stage WIP limit was removed."),
                area="workflows",
            )
        return result

    def _check_project_managers(self, projects):
        if any(
            not project.with_user(self.env.user).has_access("read")
            for project in projects
        ):
            raise AccessError(
                _("You must be able to open the Odoo Project to manage its WIP limits.")
            )
        if any(
            not project.agile_enabled
            or project._agile_role_for_user(self.env.user) != "manager"
            for project in projects
        ):
            raise AccessError(
                _("Only this project's Agile Manager can change WIP limits.")
            )


class ProjectProject(models.Model):
    _inherit = "project.project"

    def agile_board_wip(self):
        """Issue counts for the stages that have a WIP limit, for the board column badges.

        The count is the whole stage of the project, not only what the board filters show.
        """
        self.ensure_one()
        self._check_agile_backlog_access()
        limits = self.agile_wip_limit_ids
        counts = {}
        if limits:
            groups = self.env["project.task"]._read_group(
                [
                    ("project_id", "=", self.id),
                    ("agile_issue", "=", True),
                    ("active", "=", True),
                    ("stage_id", "in", limits.stage_id.ids),
                ],
                ["stage_id"],
                ["__count"],
            )
            counts = {stage.id: count for stage, count in groups}
        return {
            "project_id": self.id,
            "stages": [
                {
                    "stage_id": limit.stage_id.id,
                    "limit": limit.wip_limit,
                    "current": counts.get(limit.stage_id.id, 0),
                    "per_swimlane": limit.per_swimlane,
                }
                for limit in limits
            ],
        }
