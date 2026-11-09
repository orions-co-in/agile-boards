from odoo import api, models, _
from odoo.exceptions import AccessError


class MailMessage(models.Model):
    _name = "mail.message"
    _inherit = ["mail.message", "agile.scoped.access.mixin"]
    _agile_model_field = "model"
    _agile_parent_field = "parent_id"

    def _agile_tasks_for_message_changes(self, values_list=None):
        links = set()
        parent_ids = set()
        for message in self.sudo():
            if message.model and message.res_id:
                links.add((message.model, message.res_id))
            if message.parent_id:
                parent_ids.add(message.parent_id.id)

        values_list = values_list or []
        defaults = self.default_get(["model", "res_id", "parent_id"])
        for values in values_list:
            targets = self if self else (None,)
            for message in targets:
                model = values.get(
                    "model",
                    message.model if message else defaults.get("model"),
                )
                res_id = values.get(
                    "res_id",
                    message.res_id if message else defaults.get("res_id"),
                )
                parent_id = values.get(
                    "parent_id",
                    message.parent_id.id if message and message.parent_id
                    else defaults.get("parent_id"),
                )
                if model and res_id:
                    links.add((model, res_id))
                if parent_id:
                    parent_ids.add(parent_id)

        # A reply may inherit its issue only through a chain of parent messages.
        checked_parent_ids = set()
        while parent_ids - checked_parent_ids:
            batch_ids = parent_ids - checked_parent_ids
            checked_parent_ids |= batch_ids
            parents = self.sudo().browse(batch_ids).exists()
            for parent in parents:
                if parent.model and parent.res_id:
                    links.add((parent.model, parent.res_id))
                if parent.parent_id:
                    parent_ids.add(parent.parent_id.id)

        task_ids = {
            res_id for model, res_id in links if model == "project.task"
        }
        return self.env["project.task"].sudo().with_context(
            active_test=False
        ).browse(task_ids).exists().filtered(
            lambda task: task.agile_issue and task.project_id.agile_enabled
        )

    def _check_agile_message_mutation(self, values_list=None):
        if self.env.su:
            return
        tasks = self._agile_tasks_for_message_changes(values_list=values_list)
        for task in tasks:
            if not task.project_id.with_user(self.env.user).has_access("read"):
                raise AccessError(
                    _("You must retain native Odoo Project access to use issue chatter.")
                )
            if task.project_id._agile_role_for_user(self.env.user) not in (
                "manager", "contributor", "reviewer"
            ):
                raise AccessError(
                    _("Only Agile managers, contributors, and reviewers can change issue chatter.")
                )

    @api.model_create_multi
    def create(self, vals_list):
        defaults = self.default_get(["model", "res_id", "parent_id"])
        resolved_values = []
        for values in vals_list:
            resolved = dict(values)
            for field_name in ("model", "res_id", "parent_id"):
                if field_name not in resolved and defaults.get(field_name):
                    resolved[field_name] = defaults[field_name]
            resolved_values.append(resolved)
        self._check_agile_message_mutation(values_list=resolved_values)
        return super().create(vals_list)

    def write(self, vals):
        self._check_agile_message_mutation(values_list=[vals])
        return super().write(vals)

    def unlink(self):
        self._check_agile_message_mutation()
        return super().unlink()
