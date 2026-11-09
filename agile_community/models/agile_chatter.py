from odoo import api, models, _
from odoo.exceptions import AccessError


class MailMessage(models.Model):
    _inherit = "mail.message"

    @api.model
    def _search(
        self,
        domain,
        offset=0,
        limit=None,
        order=None,
        *,
        bypass_access=False,
        **kwargs,
    ):
        query = super()._search(
            domain,
            offset=offset,
            limit=limit,
            order=order,
            bypass_access=bypass_access,
            **kwargs,
        )
        if self.env.su or bypass_access:
            return query
        message_ids = [
            row[0]
            for row in self.env.execute_query(
                query.select(self._field_to_sql(self._table, "id"))
            )
        ]
        readable = self.browse(message_ids)._filtered_access("read")
        return readable._as_query(order)

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

    def _agile_tasks_by_message(self, messages):
        task_ids_by_message = {message.id: set() for message in messages}
        parent_by_message = {}
        for message in messages.sudo():
            if message.model == "project.task" and message.res_id:
                task_ids_by_message[message.id].add(message.res_id)
            if message.parent_id:
                parent_by_message[message.id] = message.parent_id.id

        visited_by_message = {message.id: set() for message in messages}
        while parent_by_message:
            parent_ids = set(parent_by_message.values())
            parents = {
                parent.id: parent
                for parent in self.sudo().browse(parent_ids).exists()
            }
            next_parent_by_message = {}
            for message_id, parent_id in parent_by_message.items():
                if parent_id in visited_by_message[message_id]:
                    continue
                visited_by_message[message_id].add(parent_id)
                parent = parents.get(parent_id)
                if not parent:
                    continue
                if parent.model == "project.task" and parent.res_id:
                    task_ids_by_message[message_id].add(parent.res_id)
                if parent.parent_id:
                    next_parent_by_message[message_id] = parent.parent_id.id
            parent_by_message = next_parent_by_message

        return task_ids_by_message

    def _get_forbidden_access(self, operation):
        forbidden = super()._get_forbidden_access(operation)
        if operation != "read" or self.env.su:
            return forbidden

        messages = self - forbidden
        task_ids_by_message = self._agile_tasks_by_message(messages)
        task_ids = {
            task_id
            for task_ids in task_ids_by_message.values()
            for task_id in task_ids
        }
        tasks = self.env["project.task"].sudo().with_context(
            active_test=False
        ).browse(task_ids).exists().filtered(
            lambda task: task.agile_issue and task.project_id.agile_enabled
        )
        forbidden_task_ids = set(tasks.filtered(
            lambda task: (
                task.project_id._agile_role_for_user(self.env.user) == "none"
                or not task.project_id.with_user(self.env.user).has_access("read")
                or not task.with_user(self.env.user).has_access("read")
            )
        ).ids)
        forbidden_message_ids = [
            message_id
            for message_id, linked_task_ids in task_ids_by_message.items()
            if linked_task_ids & forbidden_task_ids
        ]
        forbidden |= self.browse(forbidden_message_ids)
        return forbidden

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
