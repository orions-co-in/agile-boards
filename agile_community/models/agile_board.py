"""Several boards per project (R-1107).

The Default board is today's board and is not a record: it keeps the project's own query
(R-1101) and shows every column. Each extra board is a shared record a manager sets up.
Personal saved views and quick filters stay per project and work on every board.
"""
from datetime import datetime, time, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

MAX_BOARDS = 10  # the Default board counts as one
MAX_COLUMN_GROUPS = 8
DEFAULT_BOARD_NAME = "Default board"


class AgileBoard(models.Model):
    _name = "agile.board"
    _description = "Agile Board"
    _order = "project_id, id"

    project_id = fields.Many2one("project.project", required=True, index=True, ondelete="cascade")
    name = fields.Char(required=True, size=40)
    query_id = fields.Many2one(
        "agile.filter",
        string="Show only issues matching",
        ondelete="set null",
        domain="[('project_id', '=', project_id), ('visibility', '=', 'shared')]",
        help="The board starts limited to the issues this shared saved filter matches. People can switch it off for themselves.",
    )
    column_ids = fields.Many2many(
        "project.task.type",
        "agile_board_column_rel",
        "board_id",
        "stage_id",
        string="Columns shown",
        domain="[('project_ids', 'in', project_id)]",
        help="Leave empty to show every column. Hiding a column only hides it on this board.",
    )
    swimlane = fields.Char(
        required=True,
        default="none",
        help="none, epic, assignee, priority, component, label, or filter:<saved filter id>.",
    )
    column_group_ids = fields.One2many(
        "agile.board.column",
        "board_id",
        string="Merged columns",
        help="When set, these columns replace 'Columns shown': each holds one or more workflow statuses.",
    )

    @api.constrains("name", "project_id")
    def _check_name(self):
        for board in self:
            name = (board.name or "").strip()
            if not name:
                raise ValidationError(_("Give the board a name."))
            if name.lower() == DEFAULT_BOARD_NAME.lower():
                raise ValidationError(_("A board with this name exists."))
            others = self.search([("project_id", "=", board.project_id.id), ("id", "!=", board.id)])
            if any((other.name or "").strip().lower() == name.lower() for other in others):
                raise ValidationError(_("A board with this name exists."))

    @api.constrains("project_id")
    def _check_limit(self):
        for project in self.project_id:
            if self.search_count([("project_id", "=", project.id)]) >= MAX_BOARDS:
                raise ValidationError(_("A project keeps up to %s boards.", MAX_BOARDS))

    @api.constrains("swimlane", "query_id", "column_ids", "project_id")
    def _check_settings(self):
        for board in self:
            board.project_id._agile_check_swimlane(board.swimlane)
            if board.query_id and (
                board.query_id.project_id != board.project_id or board.query_id.visibility != "shared"
            ):
                raise ValidationError(_("Choose a shared saved filter of this project."))
            if board.column_ids - self.env["project.task.type"].with_context(active_test=False).search(
                [("project_ids", "=", board.project_id.id)]
            ):
                raise ValidationError(_("Choose columns of this project's workflow."))

    @api.constrains("column_group_ids")
    def _check_column_groups(self):
        for board in self:
            groups = board.column_group_ids
            if len(groups) > MAX_COLUMN_GROUPS:
                raise ValidationError(_("A board has at most %s columns.", MAX_COLUMN_GROUPS))
            seen = {}
            for group in groups:
                for stage in group.stage_ids:
                    if stage in seen:
                        raise ValidationError(_(
                            "%(stage)s is already in %(column)s. A status fits in one column.",
                            stage=stage.name, column=seen[stage].name,
                        ))
                    seen[stage] = group

    def _agile_column_groups(self):
        """The merged columns as the board reads them: name, statuses in workflow order, landing status."""
        self.ensure_one()
        result = []
        for group in self.column_group_ids.sorted(lambda g: (g.sequence, g.id)):
            stages = group.stage_ids.sorted(lambda stage: (stage.sequence, stage.id))
            if not stages:
                continue  # every status of it was deleted from the workflow
            landing = group.landing_stage_id if group.landing_stage_id in stages else stages[0]
            result.append({
                "name": group.name,
                "stage_ids": stages.ids,
                "landing_id": landing.id,
            })
        return result

    def _check_managers(self, projects):
        for project in projects:
            if not project.with_user(self.env.user).has_access("read"):
                raise AccessError(_("You must be able to open the Odoo Project to manage its boards."))
            if not project.agile_enabled or project._agile_role_for_user(self.env.user) != "manager":
                raise AccessError(_("Only this project's Agile Manager can change its boards."))

    @api.model_create_multi
    def create(self, vals_list):
        projects = self.env["project.project"].browse([vals.get("project_id") for vals in vals_list]).exists()
        if not self.env.su:
            self._check_managers(projects)
        boards = super().create(vals_list)
        for board in boards:
            board.project_id._agile_audit("boards", _("Board %s added.", board.name))
        return boards

    def write(self, vals):
        if "project_id" in vals:
            raise ValidationError(_("A board cannot be moved to another project."))
        if not self.env.su:
            self._check_managers(self.project_id)
        names = {board.id: board.name for board in self}
        result = super().write(vals)
        for board in self:
            board.project_id._agile_audit("boards", _("Board %s changed.", names.get(board.id) or board.name))
        return result

    def unlink(self):
        if not self.env.su:
            self._check_managers(self.project_id)
        for board in self:
            board.project_id._agile_audit("boards", _("Board %s deleted.", board.name))
        return super().unlink()


class AgileBoardColumn(models.Model):
    """One column of a board that holds one or more workflow statuses (R-1111)."""

    _name = "agile.board.column"
    _description = "Agile Board Merged Column"
    _order = "board_id, sequence, id"

    board_id = fields.Many2one("agile.board", required=True, index=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    name = fields.Char(required=True, size=40)
    stage_ids = fields.Many2many(
        "project.task.type",
        "agile_board_merged_column_rel",
        "column_id",
        "stage_id",
        string="Statuses",
    )
    landing_stage_id = fields.Many2one(
        "project.task.type",
        string="Landing status",
        help="A card dropped here from another column lands in this status. The first status when empty.",
    )

    @api.constrains("stage_ids", "landing_stage_id", "board_id")
    def _check_stages(self):
        for column in self:
            project_stages = self.env["project.task.type"].with_context(active_test=False).search(
                [("project_ids", "=", column.board_id.project_id.id)]
            )
            if column.stage_ids - project_stages:
                raise ValidationError(_("Choose statuses of this project's workflow."))
            if column.landing_stage_id and column.landing_stage_id not in column.stage_ids:
                raise ValidationError(_("The landing status must be one of the column's statuses."))

    @api.model_create_multi
    def create(self, vals_list):
        boards = self.env["agile.board"].browse([vals.get("board_id") for vals in vals_list]).exists()
        if not self.env.su:
            boards._check_managers(boards.project_id)
        columns = super().create(vals_list)
        for column in columns:
            column.board_id.project_id._agile_audit(
                "boards", _("Board %(board)s: column %(column)s added.", board=column.board_id.name, column=column.name)
            )
        return columns

    def write(self, vals):
        if not self.env.su:
            self.board_id._check_managers(self.board_id.project_id)
        result = super().write(vals)
        for column in self:
            column.board_id.project_id._agile_audit(
                "boards", _("Board %(board)s: column %(column)s changed.", board=column.board_id.name, column=column.name)
            )
        return result

    def unlink(self):
        if not self.env.su:
            self.board_id._check_managers(self.board_id.project_id)
        for column in self:
            column.board_id.project_id._agile_audit(
                "boards", _("Board %(board)s: column %(column)s removed.", board=column.board_id.name, column=column.name)
            )
        return super().unlink()


class ProjectProject(models.Model):
    _inherit = "project.project"

    def agile_board_insights(self, weeks=8):
        """Three plain numbers for the board: how old the work in progress is,
        how long finished work took lately, and how much is blocked.

        Read with the caller's own rights, so the numbers only cover issues they can see.
        """
        self.ensure_one()
        self._check_agile_backlog_access()
        today = fields.Date.context_today(self)
        weeks = max(2, min(int(weeks), 26))
        open_work = self.env["project.task"].search([
            ("project_id", "=", self.id),
            ("agile_issue", "=", True),
            ("stage_id.agile_status", "in", ["progress", "review"]),
        ])
        started = {
            event.task_id.id: event.event_at
            for event in self.env["agile.issue.metric.event"].search([
                ("task_id", "in", open_work.ids), ("event_type", "=", "started"),
            ])
        }
        aged = []
        for task in open_work:
            since = started.get(task.id) or task.date_last_stage_update
            days = self._agile_working_days_between(fields.Date.context_today(task, since), today) if since else 0
            aged.append({"id": task.id, "key": task.issue_key or task.display_name, "name": task.name, "days": days})
        aged.sort(key=lambda item: (-item["days"], item["key"]))

        monday = today - timedelta(days=today.weekday())
        first_week = monday - timedelta(weeks=weeks - 1)
        events = self.env["agile.issue.metric.event"].search([
            ("project_id", "=", self.id),
            ("event_type", "=", "completed"),
            ("event_at", ">=", datetime.combine(first_week, time.min)),
            ("cycle_time_days", "!=", False),
        ])
        buckets = {first_week + timedelta(weeks=index): [] for index in range(weeks)}
        for event in events:
            day = fields.Date.context_today(event, event.event_at)
            week = day - timedelta(days=day.weekday())
            if week in buckets:
                buckets[week].append(event.cycle_time_days)
        series = [
            {"week": fields.Date.to_string(week), "average": round(sum(values) / len(values), 1) if values else None, "count": len(values)}
            for week, values in buckets.items()
        ]
        half = weeks // 2
        recent = [v for week in list(buckets)[-half:] for v in buckets[week]]
        earlier = [v for week in list(buckets)[:-half] for v in buckets[week]]
        recent_avg = sum(recent) / len(recent) if recent else None
        earlier_avg = sum(earlier) / len(earlier) if earlier else None
        trend = "unknown"
        if recent_avg is not None and earlier_avg is not None:
            if recent_avg < earlier_avg * 0.9:
                trend = "faster"
            elif recent_avg > earlier_avg * 1.1:
                trend = "slower"
            else:
                trend = "steady"
        return {
            "in_progress": {
                "count": len(aged),
                "average_days": round(sum(item["days"] for item in aged) / len(aged), 1) if aged else 0,
                "oldest": aged[:3],
            },
            "cycle_time": {
                "series": series,
                "recent_average": round(recent_avg, 1) if recent_avg is not None else None,
                "trend": trend,
                "finished": len(events),
            },
            "blocked": {
                "count": self.env["project.task"].search_count([
                    ("project_id", "=", self.id), ("agile_issue", "=", True),
                    ("agile_is_blocked", "=", True),
                    ("stage_id.agile_status", "not in", ["done", "canceled"]),
                ]),
            },
        }

    def _agile_board_summary(self):
        """The Default board first, then the project's boards."""
        self.ensure_one()
        boards = [{"id": 0, "name": _(DEFAULT_BOARD_NAME), "is_default": True}]
        for board in self.env["agile.board"].search([("project_id", "=", self.id)]):
            boards.append({"id": board.id, "name": board.name, "is_default": False})
        return boards

    def _agile_current_board(self):
        """This person's last board of the project; an empty recordset means the Default board."""
        self.ensure_one()
        preference = self.env["agile.project.view.preference"].search(
            [("project_id", "=", self.id), ("user_id", "=", self.env.user.id)], limit=1
        )
        board = preference.last_board_id
        return board if board and board.project_id == self else self.env["agile.board"]

    def agile_board_switch(self, board_id):
        """Remember the board this person is looking at; a false id means the Default board."""
        self.ensure_one()
        self._check_agile_backlog_access()
        board = self.env["agile.board"]
        if board_id:
            board = board.search([("id", "=", board_id), ("project_id", "=", self.id)], limit=1)
            if not board:
                raise ValidationError(_("This board no longer exists."))
        values = {"last_board_id": board.id or False}
        if board:
            values["swimlane"] = board.swimlane
        Preference = self.env["agile.project.view.preference"]
        preference = Preference.search([("project_id", "=", self.id), ("user_id", "=", self.env.user.id)], limit=1)
        if preference:
            preference.write(values)
        else:
            Preference.create({"project_id": self.id, **values})
        return True

    def agile_board_copy(self, board_id):
        """A manager copies a board's settings (never its issues) under the name '<name> copy'."""
        self.ensure_one()
        self._check_agile_backlog_access()
        source = self.env["agile.board"]
        if board_id:
            source = source.search([("id", "=", board_id), ("project_id", "=", self.id)], limit=1)
            if not source:
                raise ValidationError(_("This board no longer exists."))
        base = _("%s copy", source.name or _(DEFAULT_BOARD_NAME))[:40]
        names = {name.lower() for name in self.env["agile.board"].search([("project_id", "=", self.id)]).mapped("name")}
        name, number = base, 2
        while name.lower() in names:
            suffix = f" {number}"
            name, number = base[: 40 - len(suffix)] + suffix, number + 1
        board = self.env["agile.board"].create({
            "project_id": self.id,
            "name": name,
            "query_id": (source.query_id if source else self.agile_board_query_id).id or False,
            "column_ids": [(6, 0, source.column_ids.ids)],
            "swimlane": source.swimlane if source else "none",
            "column_group_ids": [
                (0, 0, {
                    "name": group.name, "sequence": group.sequence,
                    "stage_ids": [(6, 0, group.stage_ids.ids)],
                    "landing_stage_id": group.landing_stage_id.id or False,
                })
                for group in source.column_group_ids
            ],
        })
        return {"id": board.id, "name": board.name}

    def action_agile_manage_boards(self):
        """A manager's list of the project's boards: add, rename, set the query and columns, delete."""
        self.ensure_one()
        self._check_agile_backlog_access()
        if self._agile_role_for_user() != "manager":
            raise AccessError(_("Only this project's Agile Manager can change its boards."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Boards of %s", self.name),
            "res_model": "agile.board",
            "view_mode": "list,form",
            "views": [(False, "list"), (False, "form")],
            "domain": [("project_id", "=", self.id)],
            "context": {"default_project_id": self.id},
            "target": "new",
        }
