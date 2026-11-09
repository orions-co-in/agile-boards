from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


class ProjectTaskType(models.Model):
    _inherit = "project.task.type"

    agile_status = fields.Selection(
        [
            ("backlog", "Backlog"),
            ("ready", "To Do"),
            ("progress", "In Progress"),
            ("review", "Review"),
            ("done", "Done"),
            ("canceled", "Canceled"),
        ],
        string="Agile Status",
        copy=False,
        index=True,
        help=(
            "On an Agile project, this stage meaning controls workflow actions and "
            "native task-state synchronization. Its meaning is preserved in issue history. "
            "Once Agile issues use the stage, its status cannot be changed; archive "
            "the stage instead of deleting it."
        ),
    )

    agile_is_main = fields.Boolean(
        string="Main status of its category",
        copy=False,
        help=(
            "A project can have several statuses in one category. The main one is where "
            "actions such as Start or Complete, imports and templates send an issue of that category."
        ),
    )

    @api.model
    def _agile_main_stage(self, project, status, include_archived=True):
        """The stage that stands for a category in a project (the main one, else the first)."""
        stages = self.with_context(active_test=not include_archived).search([
            ("project_ids", "=", project.id),
            ("agile_status", "=", status),
        ], order="agile_is_main desc, sequence, id", limit=1)
        return stages

    @api.constrains("name", "agile_status", "project_ids")
    def _check_agile_stage_name_unique(self):
        for stage in self.filtered("agile_status"):
            wanted = (stage.name or "").strip().lower()
            clash = self.with_context(active_test=False).search([
                ("id", "!=", stage.id),
                ("agile_status", "!=", False),
                ("project_ids", "in", stage.project_ids.ids),
            ]).filtered(lambda other: (other.name or "").strip().lower() == wanted)
            if clash:
                raise ValidationError(_("A status called %s already exists.", stage.name))

    def _agile_place_in_order(self, project):
        """Put this new stage after the last stage of its category and renumber the project's stages."""
        self.ensure_one()
        others = self.with_context(active_test=False).search([
            ("project_ids", "=", project.id), ("agile_status", "!=", False), ("id", "!=", self.id),
        ], order="sequence, id")
        last = max((i for i, stage in enumerate(others) if stage.agile_status == self.agile_status), default=len(others) - 1)
        ordered = list(others[: last + 1]) + [self] + list(others[last + 1:])
        for index, stage in enumerate(ordered):
            if stage.sequence != (index + 1) * 10:
                stage.sudo().sequence = (index + 1) * 10

    @api.constrains("agile_status", "project_ids", "agile_is_main")
    def _check_agile_status_project(self):
        for stage in self.filtered("agile_status"):
            if len(stage.project_ids) != 1 or not stage.project_ids.agile_enabled:
                raise ValidationError(
                    _("An Agile workflow stage must belong to one Agile project.")
                )
            if stage.agile_is_main and self.with_context(active_test=False).search_count([
                ("id", "!=", stage.id),
                ("project_ids", "=", stage.project_ids.id),
                ("agile_status", "=", stage.agile_status),
                ("agile_is_main", "=", True),
            ]):
                raise ValidationError(
                    _("Each category has one main status in a project.")
                )

    def _agile_check_stage_configuration_access(self, project_ids):
        if self.env.su:
            return
        projects = self.env["project.project"].browse(list(project_ids)).exists()
        if (
            not project_ids
            or set(projects.ids) != set(project_ids)
            or any(not project.with_user(self.env.user).has_access("read") for project in projects)
        ):
            raise AccessError(
                _("Only an Agile Manager with Project access can change its workflow stages.")
            )
        if self.env.user.has_group("base.group_system"):
            return
        if any(
            not project.agile_enabled
            or project._agile_role_for_user(self.env.user) != "manager"
            for project in projects
        ):
            raise AccessError(
                _("Only an Agile Manager with Project access can change its workflow stages.")
            )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            project_commands = vals.get("project_ids")
            if project_commands is None:
                project_commands = self.default_get(["project_ids"]).get(
                    "project_ids", []
                )
            project_ids = self._agile_stage_project_ids(
                project_commands, self.browse()
            )
            projects = self.env["project.project"].browse(list(project_ids)).exists()
            agile_project_ids = set(projects.filtered("agile_enabled").ids)
            if vals.get("agile_status") or agile_project_ids:
                self._agile_check_stage_configuration_access(agile_project_ids)
        stages = super().create(vals_list)
        for stage in stages.filtered(lambda item: item.agile_status and len(item.project_ids) == 1):
            has_main = self.with_context(active_test=False).search_count([
                ("project_ids", "=", stage.project_ids.id),
                ("agile_status", "=", stage.agile_status),
                ("agile_is_main", "=", True),
            ])
            if not has_main:
                stage.sudo().agile_is_main = True
        return stages

    def write(self, vals):
        for stage in self:
            current_project_ids = set(stage.project_ids.ids)
            current_agile_ids = set(
                stage.project_ids.filtered("agile_enabled").ids
            )
            target_project_ids = (
                self._agile_stage_project_ids(vals["project_ids"], stage)
                if "project_ids" in vals
                else current_project_ids
            )
            target_projects = self.env["project.project"].browse(
                list(target_project_ids)
            ).exists()
            target_agile_ids = set(target_projects.filtered("agile_enabled").ids)
            if (
                stage.agile_status
                or vals.get("agile_status")
                or current_agile_ids
                or target_agile_ids
            ):
                self._agile_check_stage_configuration_access(
                    current_agile_ids | target_agile_ids
                )
        if {"agile_status", "project_ids"} & vals.keys():
            for stage in self.filtered("agile_status"):
                used = self.env["project.task"].search_count([
                    ("stage_id", "=", stage.id),
                    ("agile_issue", "=", True),
                ])
                if used and (
                    "agile_status" in vals
                    or "project_ids" in vals
                    and self._agile_stage_project_ids(vals["project_ids"], stage)
                    != set(stage.project_ids.ids)
                ):
                    raise ValidationError(
                        _("A workflow stage used by Agile issues cannot change its status or project. Archive it instead.")
                    )
        return super().write(vals)

    @staticmethod
    def _agile_stage_project_ids(commands, stage):
        project_ids = set(stage.project_ids.ids)
        for command in commands or []:
            if command[0] == 6:
                project_ids = set(command[2])
            elif command[0] == 4:
                project_ids.add(command[1])
            elif command[0] in (2, 3):
                project_ids.discard(command[1])
            elif command[0] == 5:
                project_ids.clear()
        return project_ids

    def unlink(self):
        for stage in self.filtered(
            lambda item: item.agile_status
            or item.project_ids.filtered("agile_enabled")
        ):
            self._agile_check_stage_configuration_access(
                set(stage.project_ids.filtered("agile_enabled").ids)
            )
        used = self.filtered("agile_status")
        if used and self.env["project.task"].search_count([
            ("stage_id", "in", used.ids),
            ("agile_issue", "=", True),
        ]):
            raise ValidationError(
                _("A workflow stage used by Agile issues must be archived, not deleted.")
            )
        return super().unlink()
