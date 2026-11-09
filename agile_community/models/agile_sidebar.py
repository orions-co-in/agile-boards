import re

from odoo import _, api, models
from odoo.exceptions import AccessError, UserError

CLOSED_STATUSES = ("done", "canceled")


class ProjectProject(models.Model):
    _inherit = "project.project"

    def _agile_sidebar_is_manager(self):
        self.ensure_one()
        return self._agile_role_for_user(self.env.user) == "manager"

    @api.model
    def _agile_access_label(self, role, source):
        """"Manager · Odoo administrator" or "Contributor · Team": what the header chip says."""
        role_name = dict(self.env["agile.project.member"]._fields["role"].selection).get(role, role)
        if source == "odoo_admin":
            via = _("Odoo administrator") if self.env.user.has_group("base.group_system") or self.env.user.id == 1 else _("Agile administrator")
        else:
            via = _("Team")
        return f"{role_name} · {via}"

    def _agile_sidebar_entries(self):
        """Sidebar entries this person may open, in display order (N-101, N-104)."""
        self.ensure_one()
        entries = ["summary", "roadmap", "backlog", "board"]
        if self.use_scrum:
            entries.append("sprints")
        entries += ["mine", "reports", "releases"]
        if self._agile_sidebar_is_manager():
            entries += ["components", "settings"]
        return entries

    def agile_sidebar_data(self):
        """What the project sidebar shows: names, the entries and three counts.

        Returns ``{"enabled": False}`` for a project that is not Agile or for a person
        who is not on its team, so the sidebar stays hidden instead of raising.
        """
        self.ensure_one()
        try:
            self.check_access("read")
        except AccessError:
            return {"enabled": False}
        access_role, access_source = self._agile_access(self.env.user)
        if not self.agile_enabled or access_role == "none":
            return {"enabled": False}
        tasks = self.env["project.task"]
        backlog_domain = [
            ("project_id", "=", self.id),
            ("agile_issue", "=", True),
            ("agile_is_epic", "=", False),
            ("child_ids", "=", False),  # same leaf rule as the Backlog list (NU-32)
            ("sprint_id", "=", False),
            ("stage_id.agile_status", "not in", CLOSED_STATUSES),
        ]
        boards = self._agile_board_summary()
        active_sprints = self._agile_active_sprints()
        # One name, or a count when the project runs several sprints at once.
        sprint = (
            active_sprints[0].name
            if len(active_sprints) == 1
            else (_("%s active sprints", len(active_sprints)) if active_sprints else False)
        )
        return {
            "enabled": True,
            "id": self.id,
            "name": self.name,
            "key": self.agile_key or "",
            "method": self.agile_method,
            "sprint": sprint,
            "role": access_role,
            "access_source": access_source,
            "access_label": self._agile_access_label(access_role, access_source),
            "entries": self._agile_sidebar_entries(),
            # Boards under Board, only when the project has more than the Default board.
            "boards": boards if len(boards) > 1 else [],
            "board_id": self._agile_current_board().id or 0,
            "counts": {
                "backlog": tasks.search_count(backlog_domain),
                "blocked": tasks.search_count(self._agile_metric_domain("blocked")),
                "mine": tasks.search_count(self._agile_your_work_domain("assigned")),
                "late": self.env["agile.roadmap"].late_dependency_count(self),
            },
        }

    def agile_sidebar_action(self, entry):
        """The action for one sidebar entry; reuses the screen each button opens."""
        self.ensure_one()
        if entry not in self._agile_sidebar_entries():
            raise AccessError(_("You cannot open this screen for this project."))
        method = {
            "summary": self.action_open_agile_summary,
            "roadmap": self.action_open_agile_roadmap_page,
            "backlog": self.action_open_agile_backlog,
            "board": self.action_view_tasks,
            "sprints": self.action_sprints,
            "mine": self.action_open_agile_your_work,
            "reports": self.action_open_agile_reports,
            "releases": self._agile_sidebar_releases_action,
            "components": self.action_manage_agile_components,
            "settings": self._agile_sidebar_settings_action,
        }.get(entry) or self._agile_sidebar_extra_actions().get(entry)
        if not method:
            raise UserError(_("Unknown screen: %s", entry))
        action = method()
        if entry == "board":
            action["name"] = _("Board")
        # The web client needs "views" in an action it did not load itself.
        if action.get("type") == "ir.actions.act_window" and not action.get("views"):
            action["views"] = [
                (False, view_type) for view_type in action.get("view_mode", "list,form").split(",")
            ]
        return action

    def _agile_sidebar_extra_actions(self):
        """Hook: screens agile_pro adds to the sidebar, by entry."""
        return {}

    def _agile_sidebar_releases_action(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Releases"),
            "res_model": "project.version",
            "view_mode": "list,form",
            "domain": [("project_id", "=", self.id)],
            "context": {"default_project_id": self.id},
        }

    def _agile_sidebar_settings_action(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.name,
            "res_model": "project.project",
            "res_id": self.id,
            "views": [(False, "form")],
            "context": {"agile_sidebar_settings": True},
        }

    def agile_open_landing(self):
        """Opening a project card: Summary for an Agile team member, the board otherwise (N-103)."""
        self.ensure_one()
        if self.agile_enabled and self._agile_role_for_user(self.env.user) != "none":
            return self.action_open_agile_summary()
        return self.action_view_tasks()

    @api.model
    def agile_open_menu(self):
        """Project > Agile: the project's Summary when there is one, else a list to pick from."""
        projects = self.search([("agile_enabled", "=", True)]).filtered(
            lambda project: project._agile_role_for_user(self.env.user) != "none"
        )
        if len(projects) == 1:
            return projects.agile_open_landing()
        return {
            "type": "ir.actions.act_window",
            "name": _("Agile projects"),
            "res_model": "project.project",
            "view_mode": "kanban,list,form",
            "domain": [("id", "in", projects.ids)],
        }

    @api.model
    def _agile_suggest_key(self, name):
        """A free Project Key from the project name: Orions Project gives ORI, then ORI2 if taken."""
        letters = re.sub(r"[^A-Za-z0-9]", "", name or "").upper()
        letters = re.sub(r"^[0-9]+", "", letters)
        base = letters[:3] if len(letters) >= 2 else "PRJ"
        taken = set(
            self.with_context(active_test=False).search([("agile_key", "!=", False)]).mapped("agile_key")
        )
        key, number = base, 1
        while key in taken:
            number += 1
            key = f"{base}{number}"
        return key

    @api.onchange("name", "agile_enabled")
    def _onchange_agile_suggest_key(self):
        """Ticking Use Agile in the create dialog fills in a key to accept or change."""
        for project in self:
            if project.agile_enabled and not project.agile_key and project.name:
                project.agile_key = project._agile_suggest_key(project.name)
