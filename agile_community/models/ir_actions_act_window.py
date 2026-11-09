from odoo import models

PROJECT_TASKS_ACTION = "project.act_project_project_2_project_task_all"
AGILE_BACKLOG_ACTION = "agile_community.action_agile_backlog_url"


class IrActionsActWindow(models.Model):
    _inherit = "ir.actions.act_window"

    def _get_action_dict(self):
        """Serve the Agile board when /odoo/project/<id>/tasks is reloaded.

        Opening a project calls project.action_view_tasks(), but reloading or
        sharing its URL loads the stored core action directly. That skips the
        Agile override, so the core "Open" filter hides Done issues and the
        Agile views, filters and role limits are lost.
        """
        project = self._agile_tasks_action_project()
        if project:
            return project.with_context(
                agile_tasks_action_resolved=True
            ).action_view_tasks()
        backlog_project = self._agile_backlog_action_project()
        if backlog_project:
            # Back and reload of /odoo/<project>/agile-backlog bring the Agile Backlog, not the core list.
            return backlog_project.action_open_agile_backlog()
        return super()._get_action_dict()

    def _agile_backlog_action_project(self):
        active_id = self.env.context.get("active_id")
        if len(self) != 1 or not isinstance(active_id, int):
            return None
        if self != self.env.ref(AGILE_BACKLOG_ACTION, raise_if_not_found=False):
            return None
        project = self.env["project.project"].sudo().browse(active_id).exists()
        if not project.agile_enabled:
            return None
        return project.sudo(False)

    def _agile_tasks_action_project(self):
        context = self.env.context
        active_id = context.get("active_id")
        if (
            len(self) != 1
            or context.get("agile_tasks_action_resolved")
            or not isinstance(active_id, int)
        ):
            return None
        if self != self.env.ref(PROJECT_TASKS_ACTION, raise_if_not_found=False):
            return None
        project = self.env["project.project"].sudo().browse(active_id).exists()
        if not project.agile_enabled:
            return None
        # /web/action/load runs as sudo; role checks need the real user.
        return project.sudo(False)
