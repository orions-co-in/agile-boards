from odoo import fields, models


class ProjectProject(models.Model):
    _inherit = "project.project"

    version_ids = fields.One2many(
        comodel_name="project.version",
        inverse_name="project_id",
        string="Version",
        copy=True,
    )

    def copy(self, default=None):
        copies = super().copy(default)
        # A copied task still points at the original project's version; use the copy's version of the same name.
        for original, new in zip(self, copies):
            versions = {version.name: version for version in new.version_ids}
            for task in new.with_context(active_test=False).task_ids:
                if task.version_id and task.version_id.project_id == original:
                    replacement = versions.get(task.version_id.name)
                    if replacement:
                        task.version_id = replacement
        return copies
