import re

from odoo import api, models, tools


class ProjectTask(models.Model):
    _inherit = "project.task"

    @api.model
    def message_new(self, msg_dict, custom_values=None):
        """Mail to a project alias: a known reporter naming an issue key in the subject adds a comment
        to that issue; anything else becomes a new issue whose reporter follows it."""
        existing = self._agile_mail_existing_issue(msg_dict, custom_values or {})
        if existing:
            return existing
        task = super().message_new(msg_dict, custom_values=custom_values)
        if task.agile_issue and task.partner_id:
            task.message_subscribe(partner_ids=task.partner_id.ids)
        return task

    @api.model
    def _agile_mail_existing_issue(self, msg_dict, custom_values):
        """The issue of this project named in the subject, when the sender already follows or reported it."""
        project = self.env["project.project"].sudo().browse(custom_values.get("project_id")).exists()
        if not (project and project.agile_enabled and project.agile_key and msg_dict.get("subject")):
            return self.browse()
        keys = project._agile_issue_key_forms(msg_dict["subject"])
        if not keys:
            return self.browse()
        sender = msg_dict.get("author_id") or self.env["mail.thread"]._partner_find_from_emails_single(
            tools.email_split(msg_dict.get("email_from") or ""), no_create=True
        ).id
        if not sender:
            return self.browse()
        issue = self.sudo().with_context(active_test=False).search([
            ("project_id", "=", project.id), ("issue_key", "in", sorted(keys)),
            "|", ("partner_id", "=", sender), ("message_partner_ids", "in", [sender]),
        ], limit=1)
        return issue.with_env(self.env) if issue else self.browse()


class ProjectProjectKeys(models.Model):
    _inherit = "project.project"

    def _agile_issue_key_forms(self, text):
        """Stored key forms for every issue number of this project written in the text."""
        pattern = r"(?<![A-Za-z0-9])%s-(\d+)(?![0-9])" % re.escape(self.agile_key)
        keys = set()
        # People write WEB-12; the stored key is zero-padded (WEB-0012), so try both forms.
        for number in re.findall(pattern, text, flags=re.IGNORECASE):
            number = int(number)
            keys.update({f"{self.agile_key}-{number}", f"{self.agile_key}-{number:04d}", f"{self.agile_key}-{number:05d}"})
        return keys
