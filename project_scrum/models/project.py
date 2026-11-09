from odoo import api, fields, models
from odoo.exceptions import UserError


class ProjectProject(models.Model):
    _inherit = "project.project"

    use_scrum = fields.Boolean(string="Use Scrum", copy=False)
    allow_multiple_active_sprints = fields.Boolean(
        string="Allow several active sprints",
        copy=False,
        help="Let more than one sprint of this project be active at the same time. "
        "Off keeps the rule of one active sprint.",
    )

    scrum_estimate_unit = fields.Selection(
        [("points", "Story points"), ("hours", "Hours"), ("issues", "Issue count")],
        string="Estimate unit",
        default="points",
        required=True,
        copy=True,
        help="What this project's estimates, burndown, velocity and capacity count. "
        "Points and hours both use the Story Points number; Issue count counts every issue as 1.",
    )
    scrum_estimate_unit_changed = fields.Date(string="Estimate unit changed", readonly=True, copy=False)
    scrum_estimate_unit_before = fields.Selection(
        [("points", "Story points"), ("hours", "Hours"), ("issues", "Issue count")],
        string="Previous estimate unit",
        readonly=True,
        copy=False,
    )

    sprint_ids = fields.One2many(
        comodel_name="project.sprint",
        inverse_name="project_id",
        string="Sprints",
    )
    sprint_count = fields.Integer(compute="_compute_sprint_count")
    backlog_count = fields.Integer(compute="_compute_backlog_count")

    @api.onchange("scrum_estimate_unit")
    def _onchange_scrum_estimate_unit(self):
        if self._origin and self._origin.scrum_estimate_unit != self.scrum_estimate_unit:
            return {
                "warning": {
                    "title": self.env._("Change the estimate unit?"),
                    "message": self.env._(
                        "Sprints that are closed keep the numbers they had, counted in %(old)s. "
                        "Open sprints and new reports use the new unit from now on.",
                        old=dict(self._fields["scrum_estimate_unit"].selection)[
                            self._origin.scrum_estimate_unit
                        ],
                    ),
                }
            }

    def _compute_backlog_count(self):
        backlogs_count_by_sprint = dict(
            self.env["project.task"]._read_group(
                [
                    ("project_id", "in", self.ids),
                    ("sprint_id", "=", False),
                    ("state", "!=", "1_done"),
                ],
                ["project_id"],
                ["__count"],
            )
        )
        for project in self:
            project.backlog_count = backlogs_count_by_sprint.get(project, 0)

    def _compute_sprint_count(self):
        assigned_sprint_count = dict(
            self.env["project.sprint"]._read_group(
                [("project_id", "in", self.ids)], ["project_id"], ["__count"]
            )
        )
        for project in self:
            project.sprint_count = assigned_sprint_count.get(project, 0)

    def write(self, vals):
        if vals.get("use_scrum") is False:
            open_sprints = self.mapped("sprint_ids").filtered(
                lambda sprint: sprint.state != "done"
            )
            if open_sprints:
                raise UserError(
                    self.env._(
                        "Complete or remove every planned and active sprint before "
                        "turning off Scrum for this project."
                    )
                )
        return super().write(vals)

    def _check_scrum_enabled(self):
        if any(not project.use_scrum for project in self):
            raise UserError(
                self.env._("Turn on Scrum in this project before opening its sprints.")
            )

    def action_sprints(self):
        self.ensure_one()
        self._check_scrum_enabled()
        return {
            "name": self.env._("Sprints"),
            "type": "ir.actions.act_window",
            "res_model": "project.sprint",
            "view_mode": "list,form",
            "domain": [("project_id", "=", self.id)],
            "context": {"default_project_id": self.id},
        }

    def action_backlog(self):
        self.ensure_one()
        self._check_scrum_enabled()
        return {
            "name": self.env._("Backlog"),
            "type": "ir.actions.act_window",
            "res_model": "project.task",
            "view_mode": "list,form",
            "domain": [
                ("project_id", "=", self.id),
                ("sprint_id", "=", False),
                ("state", "!=", "1_done"),
            ],
            "context": {"default_project_id": self.id},
        }

    def write(self, vals):
        new_unit = vals.get("scrum_estimate_unit")
        if new_unit:
            for project in self.filtered(lambda p: p.scrum_estimate_unit != new_unit):
                super(ProjectProject, project).write(
                    {
                        "scrum_estimate_unit_before": project.scrum_estimate_unit,
                        "scrum_estimate_unit_changed": fields.Date.context_today(project),
                    }
                )
        if vals.get("allow_multiple_active_sprints") is False:
            for project in self.filtered("allow_multiple_active_sprints"):
                active = self.env["project.sprint"].search_count(
                    [("project_id", "=", project.id), ("state", "=", "in_progress")]
                )
                if active > 1:
                    raise UserError(
                        self.env._(
                            "%(project)s has %(count)s active sprints. Complete all but one "
                            "before switching back to a single active sprint.",
                            project=project.name,
                            count=active,
                        )
                    )
        return super().write(vals)
