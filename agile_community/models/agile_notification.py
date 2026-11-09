from odoo import Command, api, fields, models

STATUS_SUBTYPES = [
    "project.mt_task_stage", "project.mt_task_in_progress", "project.mt_task_done", "project.mt_task_canceled",
    "project.mt_task_approved", "project.mt_task_changes_requested", "project.mt_task_waiting",
]


class ProjectProject(models.Model):
    _inherit = "project.project"

    agile_watch_creator = fields.Boolean(
        string="The person who creates an issue follows it", default=True,
        help="Followers get the issue's messages. Turn off to leave people to follow issues themselves.",
    )
    agile_watch_assignees = fields.Boolean(
        string="People assigned to an issue follow it", default=True,
    )
    agile_watch_managers = fields.Boolean(
        string="Project managers follow every new issue", default=False,
    )
    agile_notify_status = fields.Boolean(
        string="Tell followers when an issue changes status", default=True,
    )
    agile_notify_comments = fields.Boolean(
        string="Tell followers about comments", default=True,
        help="People who are mentioned in a comment are always told.",
    )
    agile_notify_assignment = fields.Boolean(
        string="Tell people when an issue is assigned to them", default=True,
    )


class ProjectTask(models.Model):
    _inherit = "project.task"

    def _agile_notification_project(self):
        """The Agile project whose settings apply to this issue, or none."""
        project = self.project_id
        return project if project.agile_enabled and self.agile_issue else self.env["project.project"]

    @api.model_create_multi
    def create(self, vals_list):
        tasks = super().create(vals_list)
        for task in tasks:
            task._agile_apply_watch_defaults()
        return tasks

    def _agile_apply_watch_defaults(self):
        """Who follows a new issue, as the project's settings say."""
        self.ensure_one()
        project = self._agile_notification_project()
        if not project:
            return
        sudo = self.sudo()
        assignees = self.user_ids.partner_id
        creator = self.create_uid.partner_id
        if not project.agile_watch_creator and creator and creator not in assignees:
            sudo.message_unsubscribe(partner_ids=creator.ids)
        if not project.agile_watch_assignees and assignees:
            sudo.message_unsubscribe(partner_ids=(assignees - (creator if project.agile_watch_creator else assignees.browse())).ids)
        if project.agile_watch_managers:
            managers = project.sudo().agile_member_ids.filtered(lambda m: m.role == "manager" and m.user_id.active).user_id
            sudo.message_subscribe(partner_ids=managers.partner_id.ids)

    def _message_auto_subscribe_followers(self, updated_values, default_subtype_ids):
        # Assigned people follow the issue unless the project says otherwise.
        project = self[:1]._agile_notification_project() if self else self.env["project.project"]
        if project and not project.agile_watch_assignees:
            return []
        return super()._message_auto_subscribe_followers(updated_values, default_subtype_ids)

    @api.model
    def _task_message_auto_subscribe_notify(self, users_per_task):
        allowed = {
            task: users for task, users in users_per_task.items()
            if not (task._agile_notification_project() and not task._agile_notification_project().agile_notify_assignment)
        }
        return super()._task_message_auto_subscribe_notify(allowed)

    def _agile_message_event(self, message, msg_vals):
        """The kind of event a message is: "status", "comment" or none of the switchable ones."""
        subtype_id = msg_vals.get("subtype_id") if msg_vals and "subtype_id" in msg_vals else message.sudo().subtype_id.id
        if not subtype_id:
            return None
        if subtype_id in {self.env.ref(x).id for x in STATUS_SUBTYPES if self.env.ref(x, raise_if_not_found=False)}:
            return "status"
        message_type = msg_vals.get("message_type") if msg_vals and "message_type" in msg_vals else message.sudo().message_type
        if subtype_id == self.env.ref("mail.mt_comment").id and message_type == "comment":
            return "comment"
        return None

    def _notify_get_recipients(self, message, msg_vals=False, **kwargs):
        recipients = super()._notify_get_recipients(message, msg_vals=msg_vals, **kwargs)
        project = self._agile_notification_project() if len(self) == 1 else None
        if not project:
            return recipients
        event = self._agile_message_event(message, msg_vals)
        enabled = {"status": project.agile_notify_status, "comment": project.agile_notify_comments}
        if event is None or enabled[event]:
            return recipients
        # The event is switched off: followers are not told, people named in the message still are.
        named = set((msg_vals or {}).get("partner_ids") or message.sudo().partner_ids.ids)
        return [r for r in recipients if not r.get("is_follower") or r["id"] in named]
