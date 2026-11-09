from odoo import _, api, fields, models
from odoo.exceptions import AccessError

SPRINT_RANK = {"in_progress": 0, "draft": 1, "done": 3}
NO_SPRINT_RANK = 2
OPEN_STATUSES_EXCLUDED = ["done", "canceled"]


class ProjectProject(models.Model):
    _inherit = "project.project"

    def _check_agile_backlog_access(self):
        self.ensure_one()
        self.check_access("read")
        if not self.agile_enabled or self._agile_role_for_user() == "none":
            raise AccessError(_("You must be a member of this Agile project to open its backlog."))

    def _agile_backlog_domain(self):
        """Leaf issues of the project; unsprinted finished work is not backlog."""
        self.ensure_one()
        return [
            ("project_id", "=", self.id),
            ("agile_issue", "=", True),
            ("active", "=", True),
            ("agile_is_epic", "=", False),
            ("child_ids", "=", False),
            "|",
            ("sprint_id", "!=", False),
            ("stage_id.agile_status", "not in", OPEN_STATUSES_EXCLUDED),
        ]

    def agile_calendar_spans(self, start, end):
        """Sprints and releases of this project that touch [start, end], for the Calendar.

        Read with the caller's own rights, so people see only what they could open.
        """
        self.ensure_one()
        self._check_agile_backlog_access()
        start, end = fields.Date.to_date(start), fields.Date.to_date(end)
        spans = []
        if self.use_scrum:
            sprints = self.env["project.sprint"].search([
                ("project_id", "=", self.id),
                ("date_start", "<=", end),
                ("date_end", ">=", start),
            ])
            for sprint in sprints:
                spans.append({
                    "id": f"sprint-{sprint.id}",
                    "kind": "sprint",
                    "res_model": "project.sprint",
                    "res_id": sprint.id,
                    "title": _("Sprint: %s", sprint.name),
                    "start": fields.Date.to_string(sprint.date_start),
                    "end": fields.Date.to_string(sprint.date_end),
                    "state": sprint.state,
                })
        releases = self.env["project.version"].search([
            ("project_id", "=", self.id),
            ("release_date", ">=", start),
            ("release_date", "<=", end),
        ])
        for release in releases:
            spans.append({
                "id": f"release-{release.id}",
                "kind": "release",
                "res_model": "project.version",
                "res_id": release.id,
                "title": _("Release: %s", release.name),
                "start": fields.Date.to_string(release.release_date),
                "end": fields.Date.to_string(release.release_date),
                "state": release.state,
            })
        return spans

    def action_open_agile_backlog(self):
        self.ensure_one()
        self._check_agile_backlog_access()
        view = self.env.ref
        search_view = view("agile_community.project_task_search_agile_backlog")
        return {
            "type": "ir.actions.act_window",
            "name": _("Backlog"),
            "res_model": "project.task",
            # A stable address, so the Back button and a reload bring the Backlog again.
            "path": "agile-backlog",
            # The list is the primary view; the others are the D-710 alternates.
            "views": [
                (view("agile_community.project_task_list_agile_backlog").id, "list"),
                (view("agile_community.project_task_kanban_agile_epics").id, "kanban"),
                (view("agile_community.project_task_calendar_agile_backlog").id, "calendar"),
                (view("agile_community.project_task_pivot_agile_backlog").id, "pivot"),
                (view("agile_community.project_task_graph_agile_backlog").id, "graph"),
                (view("agile_community.project_task_activity_agile_backlog").id, "activity"),
                (False, "form"),
            ],
            # The web client reads search_view_id as [id, name]; the name is not read
            # from the view so that non-admin users do not need access to ir.ui.view.
            "search_view_id": [search_view.id, "project.task.search.agile.backlog"],
            "domain": self._agile_backlog_domain(),
            "context": {
                # active_id puts the project in the address (/odoo/<id>/agile-backlog) so Back and reload find it.
                "active_id": self.id,
                "default_project_id": self.id,
                "agile_project_view": True,
                "agile_backlog": True,
                "agile_no_sprints": not self.use_scrum,
                **({"search_default_agile_hide_completed": 1} if self.use_scrum else {}),
                # Epic children are issues, not sub-tasks, in every view of the backlog.
                "subtask_action": True,
            },
        }

    def action_backlog(self):
        """Scrum's Backlog button opens the Agile backlog on Agile projects."""
        self.ensure_one()
        if self.agile_enabled and self.use_scrum:
            return self.action_open_agile_backlog()
        return super().action_backlog()

    def agile_backlog_epics(self):
        """Epics of the project with how far their child issues have come."""
        self.ensure_one()
        self._check_agile_backlog_access()
        task_model = self.env["project.task"]
        stage_status = {
            stage.id: stage.agile_status
            for stage in self.env["project.task.type"].with_context(active_test=False).search(
                [("project_ids", "=", self.id)]
            )
        }
        common = [
            ("project_id", "=", self.id),
            ("agile_issue", "=", True),
            ("active", "=", True),
        ]
        epics = task_model.search(
            common
            + [("agile_is_epic", "=", True), ("stage_id.agile_status", "!=", "canceled")],
            order="sequence, id",
        )
        stats = {
            epic.id: {"children": 0, "done_children": 0, "points": 0.0, "done_points": 0.0}
            for epic in epics
        }
        # Leaf issues under each epic (stories without sub-tasks and the sub-tasks of stories),
        # the same leaf rule as the sprint totals (NU-41); canceled work does not count.
        by_count = self.scrum_estimate_unit == "issues"
        leaves = task_model.search(
            common
            + [
                ("agile_is_epic", "=", False),
                ("child_ids", "=", False),
                "|",
                ("parent_id", "in", epics.ids),
                ("parent_id.parent_id", "in", epics.ids),
                ("stage_id.agile_status", "!=", "canceled"),
            ]
        )
        for leaf in leaves:
            epic = leaf.parent_id if leaf.parent_id in epics else leaf.parent_id.parent_id
            entry = stats[epic.id]
            done = stage_status.get(leaf.stage_id.id) == "done"
            entry["children"] += 1
            if done:
                entry["done_children"] += 1
            if by_count:
                entry["points"] += 1
                if done:
                    entry["done_points"] += 1
            elif leaf.story_points_estimated:
                entry["points"] += leaf.story_points
                if done:
                    entry["done_points"] += leaf.story_points
        return {
            "project_id": self.id,
            "estimate_unit": self.scrum_estimate_unit,
            "epics": [
                {
                    "id": epic.id,
                    "name": epic.name,
                    "issue_key": epic.issue_key or "",
                    **{key: round(value, 2) for key, value in stats[epic.id].items()},
                }
                for epic in epics
            ],
        }

    def agile_backlog_sprints(self):
        """Group-header data for the backlog: one entry per sprint plus totals."""
        self.ensure_one()
        self._check_agile_backlog_access()
        sprints = self.env["project.sprint"].search([("project_id", "=", self.id)])
        task_model = self.env["project.task"]
        base = self._agile_backlog_domain()
        stage_status = {
            stage.id: stage.agile_status
            for stage in self.env["project.task.type"].with_context(active_test=False).search(
                [("project_ids", "=", self.id)]
            )
        }
        points = {}
        for sprint, stage, total in task_model._read_group(
            base + [("sprint_id", "in", sprints.ids)],
            ["sprint_id", "stage_id"],
            ["sprint_group_points:sum"],
        ):
            by_status = points.setdefault(sprint.id, {})
            status = stage_status.get(stage.id, "backlog")
            by_status[status] = round(by_status.get(status, 0.0) + total, 2)

        issue_counts = {
            sprint.id: count
            for sprint, count in task_model._read_group(
                base + [("sprint_id", "in", sprints.ids)], ["sprint_id"], ["__count"]
            )
        }
        rows = []
        # The point and capacity totals read every issue of the sprint; as the caller that costs a
        # record-rule check per record (about 3x slower). Team members already see all of the
        # project's issues (checked above), so the totals are the same either way.
        for sprint, totals in zip(sprints, sprints.sudo()):
            rows.append({
                "id": sprint.id,
                "name": sprint.name,
                "state": sprint.state,
                "date_start": sprint.date_start.isoformat(),
                "date_end": sprint.date_end.isoformat(),
                "goal": sprint.description or "",
                "issue_count": issue_counts.get(sprint.id, 0),
                "planned_points": totals.planned_points,
                "capacity_points": totals.capacity_points,
                "over_capacity": bool(totals.over_capacity and totals.capacity_points),
                "planning_confirmed": bool(totals.planning_confirmed),
                "planning_stale": bool(totals.planning_stale),
                "unestimated_count": totals.unestimated_issue_count,
                "points_by_status": points.get(sprint.id, {}),
                "completed_points": totals.completed_points,
                "committed_points_at_close": totals.committed_points_at_close,
                "can_manage": bool(sprint.can_manage_project_sprint),
                "can_reopen": bool(sprint.can_reopen_sprint),
                "reopen_count": sprint.reopen_count,
            })
        backlog_domain = base + [("sprint_id", "=", False)]
        issue_types = self.env["agile_community.task_type"].search([
            ("active", "=", True),
            ("is_epic", "=", False),
            "|",
            ("project_ids", "=", False),
            ("project_ids", "=", self.id),
        ])
        members = self.agile_member_ids.filtered(lambda m: m.user_id.active)
        assigned_counts = {
            user.id: count
            for user, count in task_model._read_group(base, ["user_ids"], ["__count"])
            if user
        }
        return {
            "project_id": self.id,
            "estimate_unit": self.scrum_estimate_unit,
            "can_edit": self._agile_role_for_user() in ("manager", "contributor"),
            "use_scrum": bool(self.use_scrum),
            "task_types": [{"id": t.id, "name": t.name} for t in issue_types],
            "members": [
                {"id": m.user_id.id, "name": m.user_id.name, "issue_count": assigned_counts.get(m.user_id.id, 0)}
                for m in members
            ],
            "sprints": rows,
            "backlog": {
                "issue_count": task_model.search_count(backlog_domain),
                "unestimated_count": 0 if self.scrum_estimate_unit == "issues" else task_model.search_count(
                    backlog_domain + [("story_points_estimated", "=", False)]
                ),
            },
        }


class ProjectTask(models.Model):
    _inherit = "project.task"

    # Backlog sections, the board and sprint totals all filter by sprint.
    sprint_id = fields.Many2one(index=True)

    @api.model
    def web_read_group(self, *args, **kwargs):
        result = super().web_read_group(*args, **kwargs)
        groupby = kwargs.get("groupby") or (args[1] if len(args) > 1 else [])
        if self.env.context.get("agile_backlog") and groupby and groupby[0] == "sprint_id":
            self._agile_add_empty_sprint_groups(result)
            result["groups"] = self._agile_order_sprint_groups(result["groups"])
        return result

    @api.model
    def _agile_add_empty_sprint_groups(self, result):
        """Show empty planned and active sprints so they can take a drop."""
        project_id = self.env.context.get("default_project_id")
        if not project_id:
            return
        present = {g["sprint_id"][0] for g in result["groups"] if g.get("sprint_id")}
        empty = self.env["project.sprint"].search([
            ("project_id", "=", project_id),
            ("state", "in", ["draft", "in_progress"]),
            ("id", "not in", list(present)),
        ])
        for sprint in empty:
            result["groups"].append({
                "sprint_id": (sprint.id, sprint.display_name),
                "__extra_domain": [("sprint_id", "=", sprint.id)],
                "__count": 0,
            })
        result["length"] = result.get("length", 0) + len(empty)

    @api.model
    def _agile_order_sprint_groups(self, groups):
        """Active sprint, planned sprints by start date, backlog, then completed."""
        sprint_ids = [g["sprint_id"][0] for g in groups if g.get("sprint_id")]
        sprints = {s.id: s for s in self.env["project.sprint"].browse(sprint_ids)}

        def key(group):
            if not group.get("sprint_id"):
                return (NO_SPRINT_RANK, 0, 0)
            sprint = sprints[group["sprint_id"][0]]
            return (SPRINT_RANK.get(sprint.state, 4), sprint.date_start.toordinal(), sprint.id)

        return sorted(groups, key=key)
