import json
import re
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError


# The Summary tiles, in their default order (S-934); the page and the server must agree on these ids.
SUMMARY_TILE_IDS = [
    "pulse", "counts", "status", "flow", "load", "types", "epics", "release", "activity",
]


# Board swimlanes: a fixed kind, or one saved filter as "filter:<id>" (M-1053).
# Task card field -> its name on the preference; the project default is agile_card_default_<name without show_>.
CARD_FIELDS = {
    "agile_card_show_assignee": "show_assignee",
    "agile_card_show_issue_type": "show_issue_type",
    "agile_card_show_priority": "show_priority",
    "agile_card_show_points": "show_points",
    "agile_card_show_component": "show_component",
    "agile_card_show_fix_version": "show_fix_version",
    "agile_card_show_tags": "show_tags",
    "agile_card_show_deadline": "show_deadline",
    "agile_card_show_days": "show_days",
    "agile_card_density": "density",
}
# What a card shows when it is not an Agile issue.
CARD_FALLBACK = {
    "agile_card_show_assignee": True, "agile_card_show_issue_type": True, "agile_card_show_priority": True,
    "agile_card_show_points": True, "agile_card_show_component": True, "agile_card_show_fix_version": False,
    "agile_card_show_tags": False, "agile_card_show_deadline": True, "agile_card_show_days": True,
    "agile_card_density": "comfortable",
}
SWIMLANE_PATTERN = re.compile(r"^(none|epic|assignee|priority|component|label|filter:\d+)$")


class AgileProjectViewPreference(models.Model):
    _name = "agile.project.view.preference"
    _description = "Agile Project View Preferences"
    _rec_name = "project_id"

    project_id = fields.Many2one(
        "project.project", required=True, ondelete="cascade", index=True
    )
    user_id = fields.Many2one(
        "res.users", required=True, default=lambda self: self.env.user,
        ondelete="cascade", index=True,
    )
    density = fields.Selection(
        [("comfortable", "Comfortable"), ("compact", "Compact")],
        required=True,
        default="comfortable",
    )
    swimlane = fields.Char(
        required=True,
        default="none",
        help="none, epic, assignee, priority, component, label, or filter:<saved filter id>.",
    )
    board_filters = fields.Char(
        help="Quick filters kept on the board: mine, blocked, type:<id>, epic:<id>, comma separated.",
    )
    board_views = fields.Char(
        help="The person's named Board views: a JSON list of {name, filters, swimlane}.",
    )
    summary_layout = fields.Char(
        help="The person's Summary tiles: a JSON list of {id, hidden} in the order shown. Empty means the default.",
    )
    show_assignee = fields.Boolean(default=True)
    show_issue_type = fields.Boolean(default=True)
    show_priority = fields.Boolean(default=True)
    show_points = fields.Boolean(default=True)
    show_component = fields.Boolean(default=True)
    show_fix_version = fields.Boolean(default=False)
    show_tags = fields.Boolean(default=False)
    show_deadline = fields.Boolean(default=True)
    show_days = fields.Boolean(default=True)
    last_board_id = fields.Many2one(
        "agile.board", string="Last board", ondelete="set null",
        help="The board this person looked at last. Empty means the Default board.",
    )
    card_custom = fields.Boolean(
        help="The person chose their own card fields or density. Until then the project's defaults apply.",
    )

    _project_user_preference_unique = models.Constraint(
        "unique (project_id, user_id)",
        "A user can have one Agile view preference per project.",
    )

    def _check_current_member(self):
        for preference in self:
            if (
                preference.user_id != self.env.user
                or not preference.project_id.agile_enabled
                or not preference.project_id.with_user(self.env.user).has_access("read")
                or preference.project_id._agile_role_for_user(self.env.user) == "none"
            ):
                raise AccessError(
                    _("You can manage view preferences only for your own Agile project membership.")
                )

    CARD_CHOICES = {"density", "show_assignee", "show_issue_type", "show_priority", "show_points",
                    "show_component", "show_fix_version", "show_tags", "show_deadline", "show_days"}

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals["user_id"] = self.env.user.id
            if self.CARD_CHOICES & vals.keys():
                vals["card_custom"] = True
            project = self.env["project.project"].browse(
                vals.get("project_id") or self.env.context.get("default_project_id")
            )
            if (
                not project.exists()
                or not project.agile_enabled
                or not project.with_user(self.env.user).has_access("read")
                or project._agile_role_for_user(self.env.user) == "none"
            ):
                raise AccessError(
                    _("You must be a member of an Agile project to save view preferences.")
                )
        return super().create(vals_list)

    def write(self, vals):
        self._check_current_member()
        if {"project_id", "user_id"} & vals.keys():
            raise ValidationError(_("Preference ownership and project cannot be changed."))
        if self.CARD_CHOICES & vals.keys():
            vals = {**vals, "card_custom": True}
        return super().write(vals)

    def unlink(self):
        self._check_current_member()
        return super().unlink()


class ProjectTask(models.Model):
    _inherit = "project.task"

    agile_card_show_assignee = fields.Boolean(compute="_compute_agile_view_preferences")
    agile_card_show_issue_type = fields.Boolean(compute="_compute_agile_view_preferences")
    agile_card_show_priority = fields.Boolean(compute="_compute_agile_view_preferences")
    agile_card_show_points = fields.Boolean(compute="_compute_agile_view_preferences")
    agile_card_show_component = fields.Boolean(compute="_compute_agile_view_preferences")
    agile_card_show_fix_version = fields.Boolean(compute="_compute_agile_view_preferences")
    agile_card_show_tags = fields.Boolean(compute="_compute_agile_view_preferences")
    agile_card_show_deadline = fields.Boolean(compute="_compute_agile_view_preferences")
    agile_card_show_days = fields.Boolean(compute="_compute_agile_view_preferences")
    agile_days_in_status = fields.Integer(compute="_compute_agile_days_in_status")
    agile_card_density = fields.Selection(
        [("comfortable", "Comfortable"), ("compact", "Compact")],
        compute="_compute_agile_view_preferences",
    )
    agile_card_color = fields.Char(compute="_compute_agile_card_color")
    agile_card_color_text = fields.Char(compute="_compute_agile_card_color")
    agile_lane_assignee = fields.Char(compute="_compute_agile_lanes")
    agile_lane_epic = fields.Char(compute="_compute_agile_lanes")
    agile_lane_priority = fields.Char(compute="_compute_agile_lanes")
    agile_lane_component = fields.Char(compute="_compute_agile_lanes")
    agile_lane_label = fields.Char(compute="_compute_agile_lanes")

    @api.depends(
        "user_ids", "parent_id.name", "parent_id.issue_key", "priority", "agile_component_id", "tag_ids.name",
    )
    def _compute_agile_lanes(self):
        """Labels for board swimlanes: the first assignee, the epic, priority, component and first label."""
        priorities = dict(self._fields["priority"].selection)
        for task in self:
            task.agile_lane_priority = priorities.get(task.priority, "")
            task.agile_lane_component = task.agile_component_id.name or ""
            task.agile_lane_label = min(task.tag_ids.mapped("name"), default="")
            task.agile_lane_assignee = task.user_ids[:1].name or ""
            parent = task.parent_id
            task.agile_lane_epic = (
                f"{parent.issue_key} {parent.name}" if parent.issue_key else parent.name
            ) or ""

    @api.depends_context("uid")
    @api.depends(
        "project_id",
        "project_id.agile_card_default_assignee", "project_id.agile_card_default_issue_type",
        "project_id.agile_card_default_priority", "project_id.agile_card_default_points",
        "project_id.agile_card_default_component", "project_id.agile_card_default_fix_version",
        "project_id.agile_card_default_tags", "project_id.agile_card_default_deadline",
        "project_id.agile_card_default_density", "project_id.agile_card_default_days",
    )
    def _compute_agile_view_preferences(self):
        projects = self.filtered("agile_issue").mapped("project_id")
        preferences = self.env["agile.project.view.preference"].search([
            ("project_id", "in", projects.ids),
            ("user_id", "=", self.env.user.id),
        ])
        by_project = {pref.project_id.id: pref for pref in preferences}
        for task in self:
            preference = by_project.get(task.project_id.id) if task.agile_issue else False
            project = task.project_id
            for field_name, preference_name in CARD_FIELDS.items():
                if not task.agile_issue:
                    value = CARD_FALLBACK[field_name]
                elif preference and preference.card_custom:
                    value = getattr(preference, preference_name)
                else:
                    value = getattr(project, "agile_card_default_" + preference_name.removeprefix("show_"))
                setattr(task, field_name, value)

    @api.depends(
        "date_last_stage_update", "state", "project_id.agile_workday_mon", "project_id.agile_workday_tue",
        "project_id.agile_workday_wed", "project_id.agile_workday_thu", "project_id.agile_workday_fri",
        "project_id.agile_workday_sat", "project_id.agile_workday_sun",
    )
    def _compute_agile_days_in_status(self):
        """Working days since the issue entered its status; finished work does not age."""
        today = fields.Date.context_today(self)
        for task in self:
            task.agile_days_in_status = 0
            if task.agile_issue and task.date_last_stage_update and task.state not in ("1_done", "1_canceled"):
                since = fields.Date.context_today(task, task.date_last_stage_update)
                task.agile_days_in_status = task.project_id._agile_working_days_between(since, today)

    @api.depends(
        "project_id.agile_card_color_by", "project_id.agile_workday_mon", "project_id.agile_workday_tue",
        "project_id.agile_workday_wed", "project_id.agile_workday_thu", "project_id.agile_workday_fri",
        "project_id.agile_workday_sat", "project_id.agile_workday_sun", "priority", "tag_ids.name", "tag_ids.color", "date_deadline", "state",
    )
    def _compute_agile_card_color(self):
        """A colour cue for the card: a token for the stylesheet and the same fact as text."""
        today = fields.Date.context_today(self)
        priorities = dict(self._fields["priority"].selection)
        for task in self:
            token = text = ""
            mode = task.project_id.agile_card_color_by if task.agile_issue else "none"
            if mode == "priority" and task.priority in ("2", "3"):
                token, text = ("urgent" if task.priority == "3" else "high"), priorities.get(task.priority, "")
            elif mode == "label" and task.tag_ids:
                tag = min(task.tag_ids, key=lambda t: t.name or "")
                token, text = f"tag-{tag.color % 12}", _("Label: %s", tag.name)
            elif mode == "due" and task.date_deadline and task.state not in ("1_done", "1_canceled"):
                due = fields.Date.context_today(task, task.date_deadline)
                if due < today:
                    token, text = "overdue", _("Overdue")
                elif task.project_id._agile_working_days_between(today, due) <= 3:
                    token, text = "soon", _("Due soon")
            task.agile_card_color = token
            task.agile_card_color_text = text


class ProjectProject(models.Model):
    _inherit = "project.project"

    agile_card_default_assignee = fields.Boolean("Show assignee", default=True)
    agile_card_default_issue_type = fields.Boolean("Show issue type", default=True)
    agile_card_default_priority = fields.Boolean("Show priority", default=True)
    agile_card_default_points = fields.Boolean("Show story points", default=True)
    agile_card_default_component = fields.Boolean("Show component", default=True)
    agile_card_default_fix_version = fields.Boolean("Show fix version", default=False)
    agile_card_default_tags = fields.Boolean("Show labels", default=False)
    agile_card_default_deadline = fields.Boolean("Show due date", default=True)
    agile_card_default_days = fields.Boolean("Show days in status", default=True)
    agile_card_default_density = fields.Selection(
        [("comfortable", "Comfortable"), ("compact", "Compact")], string="Card density",
        required=True, default="comfortable",
    )
    agile_workday_mon = fields.Boolean("Monday", default=True)
    agile_workday_tue = fields.Boolean("Tuesday", default=True)
    agile_workday_wed = fields.Boolean("Wednesday", default=True)
    agile_workday_thu = fields.Boolean("Thursday", default=True)
    agile_workday_fri = fields.Boolean("Friday", default=True)
    agile_workday_sat = fields.Boolean("Saturday", default=False)
    agile_workday_sun = fields.Boolean("Sunday", default=False)
    agile_kanban_backlog_column = fields.Boolean(
        string="Show a Backlog column on the board",
        help="Kanban projects only. The issues in the Backlog status stay on the Backlog screen either way.",
    )
    agile_card_color_by = fields.Selection(
        [("none", "No colour"), ("priority", "Priority"), ("label", "First label"), ("due", "Due date")],
        string="Colour cards by", required=True, default="none",
        help="A coloured edge on each card. The same fact is also written as text for screen readers.",
    )
    agile_board_query_id = fields.Many2one(
        "agile.filter",
        string="Board query",
        ondelete="set null",
        copy=False,
        domain="[('project_id', '=', id), ('visibility', '=', 'shared')]",
        help="The board starts limited to the issues this shared saved filter matches. "
        "Each person can switch it off for themselves.",
    )

    def _agile_apply_view_preference(self, action):
        self.ensure_one()
        if not self.agile_enabled:
            return action
        preference = self.env["agile.project.view.preference"].search(
            [("project_id", "=", self.id), ("user_id", "=", self.env.user.id)],
            limit=1,
        )
        # The board draws swimlanes itself; it only needs to know which kind.
        action.setdefault("context", {})["agile_swimlane"] = (
            preference.swimlane if preference else "none"
        )
        return action

    BOARD_FILTER_PATTERN = re.compile(r"^(mine|blocked|canceled|review|due|type:\d+|epic:\d+|sprint:\d+)$")

    MAX_BOARD_VIEWS = 10

    def _agile_board_views(self, preference):
        try:
            saved = json.loads(preference.board_views or "[]") if preference else []
        except ValueError:
            saved = []
        views = []
        for entry in saved if isinstance(saved, list) else []:
            if isinstance(entry, dict) and entry.get("name"):
                views.append({
                    "name": str(entry["name"]),
                    "filters": [k for k in entry.get("filters", []) if isinstance(k, str)],
                    "swimlane": entry["swimlane"] if SWIMLANE_PATTERN.match(str(entry.get("swimlane"))) else "none",
                })
        return views

    def _agile_store_board_views(self, views):
        Preference = self.env["agile.project.view.preference"]
        preference = Preference.search(
            [("project_id", "=", self.id), ("user_id", "=", self.env.user.id)], limit=1,
        )
        value = json.dumps(views) if views else False
        if preference:
            preference.write({"board_views": value})
        elif value:
            Preference.create({"project_id": self.id, "board_views": value})
        return views

    def _agile_check_swimlane(self, swimlane):
        if not isinstance(swimlane, str) or not SWIMLANE_PATTERN.match(swimlane):
            raise ValidationError(_("Unknown swimlane."))
        if swimlane.startswith("filter:"):
            saved = self.env["agile.filter"].search(
                [("id", "=", int(swimlane[7:])), ("project_id", "=", self.id)], limit=1
            )
            if not saved:
                raise ValidationError(_("Choose a saved filter of this project."))

    def agile_board_lane_filters(self):
        """The saved filters this person may use as swimlanes on the board."""
        self.ensure_one()
        self._check_agile_backlog_access()
        return [
            {"id": f.id, "name": f.name}
            for f in self.env["agile.filter"].search([("project_id", "=", self.id)], limit=30)
        ]

    def agile_board_filter_ids(self, filter_id):
        """Ids of the project's issues one saved filter matches, as the person may read them."""
        self.ensure_one()
        self._check_agile_backlog_access()
        saved = self.env["agile.filter"].search([("id", "=", filter_id), ("project_id", "=", self.id)], limit=1)
        if not saved:
            raise ValidationError(_("Choose a saved filter of this project."))
        return {
            "name": saved.name,
            "ids": self.env["project.task"].search(saved._issue_domain(), limit=5000).ids,
        }

    def agile_save_board_view(self, name, filters, swimlane):
        """Keep the current filters and swimlane under a name; the same name replaces the older view."""
        self.ensure_one()
        self._check_agile_backlog_access()
        name = (name or "").strip()
        if not name:
            raise ValidationError(_("Give the view a name."))
        if len(name) > 40:
            raise ValidationError(_("A view name has up to 40 characters."))
        keys = [key for key in (filters or []) if isinstance(key, str)]
        if len(keys) > 8 or any(not self.BOARD_FILTER_PATTERN.match(key) for key in keys):
            raise ValidationError(_("Unknown board filter."))
        self._agile_check_swimlane(swimlane)
        preference = self.env["agile.project.view.preference"].search(
            [("project_id", "=", self.id), ("user_id", "=", self.env.user.id)], limit=1,
        )
        views = [v for v in self._agile_board_views(preference) if v["name"].lower() != name.lower()]
        if len(views) >= self.MAX_BOARD_VIEWS:
            raise ValidationError(_("You can keep %s views. Delete one first.", self.MAX_BOARD_VIEWS))
        views.append({"name": name, "filters": list(dict.fromkeys(keys)), "swimlane": swimlane})
        return self._agile_store_board_views(views)

    def agile_delete_board_view(self, name):
        self.ensure_one()
        self._check_agile_backlog_access()
        preference = self.env["agile.project.view.preference"].search(
            [("project_id", "=", self.id), ("user_id", "=", self.env.user.id)], limit=1,
        )
        views = [v for v in self._agile_board_views(preference) if v["name"].lower() != (name or "").strip().lower()]
        return self._agile_store_board_views(views)

    def _agile_board_query_data(self):
        """The saved query the board starts limited to, or None; a query that no longer runs has no domain."""
        self.ensure_one()
        board = self._agile_current_board()
        query = board.query_id if board else self.agile_board_query_id
        if not query:
            return None
        try:
            domain = query._issue_domain()
        except (AccessError, UserError):
            domain = None
        return {"id": query.id, "name": query.name, "domain": domain}

    def _agile_board_settings(self):
        """The current board: its name, columns shown (empty means all) and starting swimlane."""
        self.ensure_one()
        board = self._agile_current_board()
        groups = board._agile_column_groups() if board else []
        return {
            "id": board.id or 0,
            "name": board.name or _("Default board"),
            "is_default": not board,
            # Merged columns replace the simple list; the stages they hold are the ones shown.
            "column_ids": [stage for group in groups for stage in group["stage_ids"]] or board.column_ids.ids,
            "column_groups": groups,
            "swimlane": board.swimlane if board else None,
        }

    def _agile_board_query_choices(self):
        """What a manager may pick as the board query: the project's shared saved filters."""
        self.ensure_one()
        if self._agile_role_for_user() != "manager":
            return []
        saved = self.env["agile.filter"].search(
            [("project_id", "=", self.id), ("visibility", "=", "shared")], limit=30
        )
        return [{"id": f.id, "name": f.name} for f in saved]

    def write(self, vals):
        card_settings = {"agile_card_color_by", "agile_card_default_density", "agile_kanban_backlog_column"} | {
            name for name in vals if name.startswith(("agile_card_default_", "agile_workday_"))
        }
        if card_settings & vals.keys() and not self.env.su:
            if any(
                project.agile_enabled and project._agile_role_for_user(self.env.user) != "manager"
                for project in self
            ):
                raise AccessError(_("Only this project's Agile Manager can change how its cards look."))
        return super().write(vals)

    @api.constrains(
        "agile_workday_mon", "agile_workday_tue", "agile_workday_wed", "agile_workday_thu",
        "agile_workday_fri", "agile_workday_sat", "agile_workday_sun",
    )
    def _check_agile_workdays(self):
        for project in self:
            if not any(project._agile_workdays()):
                raise ValidationError(_("Choose at least one working day."))

    def _agile_workdays(self):
        """Seven flags, Monday first."""
        self.ensure_one()
        return [
            self.agile_workday_mon, self.agile_workday_tue, self.agile_workday_wed, self.agile_workday_thu,
            self.agile_workday_fri, self.agile_workday_sat, self.agile_workday_sun,
        ]

    def _agile_working_days_between(self, start, end):
        """Working days after `start` up to and including `end`; 0 when `end` is not later."""
        flags = self._agile_workdays() if self else [True] * 7
        if not any(flags):
            flags = [True] * 7
        days = (end - start).days
        return sum(1 for offset in range(1, days + 1) if flags[(start + timedelta(days=offset)).weekday()])

    def agile_set_board_query(self, filter_id):
        """A manager limits the board to one shared saved filter, or clears the limit with a false id."""
        self.ensure_one()
        self._check_agile_backlog_access()
        if self._agile_role_for_user() != "manager":
            raise AccessError(_("Only project managers can change the board's query."))
        saved = self.env["agile.filter"]
        if filter_id:
            saved = saved.search(
                [("id", "=", filter_id), ("project_id", "=", self.id), ("visibility", "=", "shared")], limit=1
            )
            if not saved:
                raise ValidationError(_("Choose a shared saved filter of this project."))
        board = self._agile_current_board()
        if saved != (board.query_id if board else self.agile_board_query_id):
            if board:
                board.write({"query_id": saved.id or False})
            else:
                self.sudo().write({"agile_board_query_id": saved.id or False})
            self._agile_audit(
                "boards",
                _("Board query set to %s.", saved.name) if saved else _("Board query removed."),
            )
        return self._agile_board_query_data()

    def agile_board_options(self):
        """What the board filter bar needs: the user's saved choices and the pick lists."""
        self.ensure_one()
        self._check_agile_backlog_access()
        preference = self.env["agile.project.view.preference"].search(
            [("project_id", "=", self.id), ("user_id", "=", self.env.user.id)],
            limit=1,
        )
        issue_types = self.env["agile_community.task_type"].search([
            ("active", "=", True),
            ("is_epic", "=", False),
            "|",
            ("project_ids", "=", False),
            ("project_ids", "=", self.id),
        ])
        epics = self.agile_backlog_epics()["epics"]
        return {
            "project_id": self.id,
            "swimlane": preference.swimlane if preference else "none",
            "lane_filters": self.agile_board_lane_filters(),
            "views": self._agile_board_views(preference),
            "boards": self._agile_board_summary(),
            "board": self._agile_board_settings(),
            "query": self._agile_board_query_data(),
            "can_edit_query": self._agile_role_for_user() == "manager",
            "query_choices": self._agile_board_query_choices(),
            "filters": [
                key for key in (preference.board_filters or "").split(",") if key
            ] if preference else [],
            "task_types": [{"id": t.id, "name": t.name} for t in issue_types],
            # More than one only when the project allows several active sprints.
            "sprints": [{"id": sprint.id, "name": sprint.name} for sprint in self._agile_active_sprints()],
            "epics": [
                {"id": e["id"], "name": e["name"], "issue_key": e["issue_key"]}
                for e in epics
            ],
        }

    def agile_summary_layout(self):
        """The current user's Summary tiles for this project: every known tile, in order, with its hidden flag."""
        self.ensure_one()
        self._check_agile_backlog_access()
        preference = self.env["agile.project.view.preference"].search(
            [("project_id", "=", self.id), ("user_id", "=", self.env.user.id)], limit=1,
        )
        saved = []
        try:
            saved = json.loads(preference.summary_layout or "[]") if preference else []
        except ValueError:
            saved = []
        layout, seen = [], set()
        for entry in saved if isinstance(saved, list) else []:
            tile = entry.get("id") if isinstance(entry, dict) else None
            if tile in SUMMARY_TILE_IDS and tile not in seen:
                seen.add(tile)
                layout.append({"id": tile, "hidden": bool(entry.get("hidden"))})
        # A tile added in a later release, or missing from an old layout, shows at the end.
        layout += [{"id": tile, "hidden": False} for tile in SUMMARY_TILE_IDS if tile not in seen]
        return layout

    def agile_save_summary_layout(self, layout):
        """Remember the order and hidden tiles of the current user's Summary; None resets to the default."""
        self.ensure_one()
        self._check_agile_backlog_access()
        value = False
        if layout is not None:
            if not isinstance(layout, list):
                raise ValidationError(_("Unknown Summary layout."))
            clean, seen = [], set()
            for entry in layout:
                tile = entry.get("id") if isinstance(entry, dict) else None
                if tile not in SUMMARY_TILE_IDS or tile in seen:
                    raise ValidationError(_("Unknown Summary tile."))
                seen.add(tile)
                clean.append({"id": tile, "hidden": bool(entry.get("hidden"))})
            if clean and all(entry["hidden"] for entry in clean) and len(clean) == len(SUMMARY_TILE_IDS):
                raise ValidationError(_("Keep at least one tile."))
            value = json.dumps(clean)
        Preference = self.env["agile.project.view.preference"]
        preference = Preference.search(
            [("project_id", "=", self.id), ("user_id", "=", self.env.user.id)], limit=1,
        )
        if preference:
            preference.write({"summary_layout": value})
        elif value:
            Preference.create({"project_id": self.id, "summary_layout": value})
        return self.agile_summary_layout()

    def agile_save_board_options(self, swimlane=None, filters=None):
        """Remember the swimlane and quick filters of the current user for this project."""
        self.ensure_one()
        self._check_agile_backlog_access()
        values = {}
        if swimlane is not None:
            self._agile_check_swimlane(swimlane)
            values["swimlane"] = swimlane
        if filters is not None:
            keys = [key for key in filters if isinstance(key, str)]
            if len(keys) > 8 or any(not self.BOARD_FILTER_PATTERN.match(key) for key in keys):
                raise ValidationError(_("Unknown board filter."))
            values["board_filters"] = ",".join(dict.fromkeys(keys))
        Preference = self.env["agile.project.view.preference"]
        preference = Preference.search(
            [("project_id", "=", self.id), ("user_id", "=", self.env.user.id)],
            limit=1,
        )
        if preference:
            preference.write(values)
        else:
            Preference.create({"project_id": self.id, **values})
        return True

    def action_agile_view_preferences(self):
        self.ensure_one()
        self.check_access("read")
        if (
            not self.agile_enabled
            or self._agile_role_for_user(self.env.user) == "none"
        ):
            raise AccessError(
                _("Only members of this Agile project can manage their board preferences.")
            )
        Preference = self.env["agile.project.view.preference"]
        preference = Preference.search(
            [("project_id", "=", self.id), ("user_id", "=", self.env.user.id)],
            limit=1,
        )
        if not preference:
            preference = Preference.create({"project_id": self.id})
        return {
            "type": "ir.actions.act_window",
            "name": _("My Board Preferences"),
            "res_model": "agile.project.view.preference",
            "view_mode": "form",
            "res_id": preference.id,
            "target": "new",
        }
