from odoo import api, models, _
from odoo.exceptions import AccessError
from odoo.fields import Domain


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    def _access_domain(self, operation):
        domain = super()._access_domain(operation)
        if operation != "read" or self.env.su or domain.is_false():
            return domain
        hidden = Domain.TRUE
        for model_name, ids in self.env["project.project"]._agile_hidden_documents().items():
            hidden &= Domain("res_model", "!=", model_name) | Domain("res_id", "not in", sorted(ids))
        # a public attachment (a logo, a web asset) stays readable
        return domain & (Domain("public", "=", True) | hidden)

    def _agile_linked_tasks(self, attachments=None, values_list=None):
        """Return Agile tasks linked before or after an attachment mutation."""
        links = set()
        attachments = attachments or self
        values_list = values_list or []
        for attachment in attachments:
            if attachment.res_model == "project.task" and attachment.res_id:
                links.add((attachment.res_model, attachment.res_id))
            for values in values_list:
                model = values.get("res_model", attachment.res_model)
                record_id = values.get("res_id", attachment.res_id)
                if model == "project.task" and record_id:
                    links.add((model, record_id))
        for values in values_list or []:
            model = values.get("res_model")
            record_id = values.get("res_id")
            if model == "project.task" and record_id:
                links.add((model, record_id))
        if not links:
            return self.env["project.task"]

        task_ids = {record_id for _model, record_id in links}
        return self.env["project.task"].sudo().with_context(
            active_test=False
        ).browse(task_ids).exists().filtered(
            lambda task: task.agile_issue and task.project_id.agile_enabled
        )

    def _check_agile_attachment_mutation(self, tasks):
        if self.env.su:
            return
        for task in tasks:
            project = task.project_id.with_user(self.env.user)
            issue = task.with_user(self.env.user)
            if not project.has_access("read"):
                raise AccessError(
                    _("You must retain native Odoo Project access to change issue attachments.")
                )
            if not issue.has_access("read"):
                raise AccessError(
                    _("You must be able to open the issue to change its attachments.")
                )
            if self.env.user.has_group("base.group_system"):
                continue
            if project._agile_role_for_user(self.env.user) not in (
                "manager", "contributor", "reviewer"
            ):
                raise AccessError(
                    _("Only Agile managers, contributors, and reviewers can change issue attachments.")
                )

    @api.model_create_multi
    def create(self, vals_list):
        tasks = self._agile_linked_tasks(values_list=vals_list)
        self._check_agile_attachment_mutation(tasks)
        return super().create(vals_list)

    def write(self, vals):
        tasks = self._agile_linked_tasks()
        tasks |= self._agile_linked_tasks(values_list=[vals])
        self._check_agile_attachment_mutation(tasks)
        return super().write(vals)

    def unlink(self):
        self._check_agile_attachment_mutation(self._agile_linked_tasks())
        return super().unlink()
