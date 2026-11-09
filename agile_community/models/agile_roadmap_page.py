import csv
import io
import re
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from .agile_filter import _safe_cell

DONE_STATUSES = ("done", "canceled")


class ProjectProject(models.Model):
    _inherit = "project.project"

    def action_open_agile_roadmap_page(self):
        self.ensure_one()
        self._check_agile_roadmap_access()
        return {
            "type": "ir.actions.client",
            "tag": "agile_community.roadmap",
            "name": _("Roadmap"),
            "params": {"project_ids": [self.id]},
            # Kept in the breadcrumb: params are lost when the page is reopened with the Back button.
            "context": {"active_id": self.id, "default_project_id": self.id},
        }


class AgileRoadmap(models.AbstractModel):
    """Data for the Roadmap page: epics with their issues, sprints, releases and dependencies."""

    _name = "agile.roadmap"
    _description = "Agile Roadmap"

    @api.model
    def _projects(self, project_ids):
        """Agile projects the person belongs to. One asked-for project must be allowed; many are filtered."""
        Project = self.env["project.project"]
        if project_ids:
            projects = Project.browse(project_ids).exists()
            if len(projects) == 1:
                projects._check_agile_roadmap_access()
                return projects
        else:
            projects = Project.search([("agile_enabled", "=", True)])
        return projects.filtered(
            lambda p: p.has_access("read") and p.agile_enabled and p._agile_role_for_user(self.env.user) != "none"
        )

    @api.model
    def roadmap_projects(self):
        """The projects the picker offers: every Agile project the person can open."""
        projects = self._projects([])
        return [{"id": p.id, "name": p.name} for p in projects.sorted("name")]

    @api.model
    def roadmap_data(self, project_ids=None, hide_done=False, epics_only=False):
        projects = self._projects(list(project_ids or []))
        if not projects:
            raise UserError(_("Open the roadmap from an Agile project."))
        Task = self.env["project.task"]
        issues = Task.search([
            ("project_id", "in", projects.ids), ("agile_issue", "=", True), ("active", "=", True),
            ("agile_planned_start", "!=", False),
        ])
        epics_all = Task.search([
            ("project_id", "in", projects.ids), ("agile_issue", "=", True), ("agile_is_epic", "=", True),
            ("active", "=", True),
        ])
        children = issues.filtered(lambda t: not t.agile_is_epic)
        dated = issues | epics_all.filtered("agile_planned_start")
        deps, circular = self._dependencies(dated, children | epics_all)
        late_ids = {d["to"] for d in deps if d["late"]}
        info = self._row_info(deps, {t.id: t for t in dated})
        rows_by_project = []
        unscheduled = 0
        for project in projects.sorted("name"):
            rows = []
            project_epics = epics_all.filtered(lambda e: e.project_id == project)
            for epic in project_epics.sorted(lambda e: (e.sequence, e.id)):
                kids = children.filtered(lambda t: t.parent_id == epic)
                if hide_done:
                    kids = kids.filtered(lambda t: t.agile_status not in ("done", "canceled"))
                row = self._epic_row(epic, kids, late_ids, circular, epics_only, info)
                if row:
                    rows.append(row)
                else:
                    unscheduled += 1
            loose = children.filtered(
                lambda t: t.project_id == project and not (t.parent_id and t.parent_id.agile_is_epic)
            )
            if hide_done:
                loose = loose.filtered(lambda t: t.agile_status not in ("done", "canceled"))
            if loose and not epics_only:
                rows.append({
                    "kind": "none", "id": 0, "key": "", "name": _("No epic"), "start": None, "end": None,
                    "done": 0, "total": 0, "late": False, "circular": False,
                    "children": [self._issue_row(t, late_ids, circular, info) for t in loose.sorted("agile_planned_start")],
                })
            rows_by_project.append({
                "id": project.id, "name": project.name, "rows": rows, "rollup": self._rollup(project),
                "can_move": project._agile_allows("roadmap_dates"),
            })
        sprints = self.env["project.sprint"].search([("project_id", "in", projects.ids), ("date_start", "!=", False)])
        releases = self.env["project.version"].search(
            [("project_id", "in", projects.ids), ("release_date", "!=", False), ("active", "=", True)])
        return {
            "plan_available": False,  # agile_pro adds the Plan view
            "projects": rows_by_project,
            "sprints": [
                {"id": s.id, "name": s.name, "project": s.project_id.name, "start": fields.Date.to_string(s.date_start),
                 "end": fields.Date.to_string(s.date_end or s.date_start)}
                for s in sprints.sorted("date_start")
            ],
            "releases": [
                {"id": r.id, "name": r.name, "project": r.project_id.name, "date": fields.Date.to_string(r.release_date)}
                for r in releases.sorted("release_date")
            ],
            "dependencies": deps,
            "unscheduled": unscheduled,
            "multi": len(projects) > 1,
            "today": fields.Date.to_string(fields.Date.context_today(self)),
        }

    @api.model
    def roadmap_csv(self, project_ids=None, hide_done=False, epics_only=False):
        """The roadmap as CSV: one line for each item the person can read on the current view.

        It uses the screen's own data, so the picker, Hide done, Epics only and every
        permission apply. Blocked by lists the open blockers the person can read.
        """
        data = self.roadmap_data(project_ids, hide_done=hide_done, epics_only=epics_only)
        items = []
        for project in data["projects"]:
            for row in project["rows"]:
                for item in ([row] if row["kind"] != "none" else []) + row["children"]:
                    items.append((project["name"], item))
        types = {
            t.id: t.agile_task_type_id.name or ""
            for t in self.env["project.task"].browse([item["id"] for _name, item in items])
        }
        statuses = dict(self.env["project.task"]._fields["agile_status"]._description_selection(self.env))
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            _("Project"), _("Key"), _("Title"), _("Type"), _("Status"), _("Planned start"), _("Planned end"),
            _("Blocked by"), _("Collision days"), _("Earliest valid start"),
        ])
        for project_name, item in items:
            collision = item.get("collision")
            writer.writerow([_safe_cell(value) for value in (
                project_name, item["key"], item["name"], types.get(item["id"], ""),
                statuses.get(item["status"], item["status"]), item["start"], item["end"],
                " ".join(b["key"] for b in item.get("blocked_by", [])),
                collision["days"] if collision else "", collision["earliest_start"] if collision else "",
            )])
        names = [p["name"] for p in data["projects"]]
        slug = re.sub(r"[^A-Za-z0-9]+", "-", names[0] if len(names) == 1 else "").strip("-").lower()
        return {
            "filename": f"roadmap-{slug}.csv" if slug else "roadmap.csv",
            "content": output.getvalue(), "count": len(items),
        }

    @api.model
    def _rollup(self, project):
        """Epic and issue progress of one project, for its heading in the cross-project view."""
        Task = self.env["project.task"]
        base = [("project_id", "=", project.id), ("agile_issue", "=", True), ("active", "=", True)]
        return {
            "epics_total": Task.search_count(base + [("agile_is_epic", "=", True)]),
            "epics_done": Task.search_count(base + [("agile_is_epic", "=", True), ("agile_status", "=", "done")]),
            "issues_total": Task.search_count(base + [("agile_is_epic", "=", False)]),
            "issues_done": Task.search_count(base + [("agile_is_epic", "=", False), ("agile_status", "=", "done")]),
        }

    @api.model
    def _issue_row(self, task, late_ids, circular, info=None):
        return {
            "kind": "issue", "id": task.id, "key": task.issue_key or "", "name": task.name,
            "start": fields.Date.to_string(task.agile_planned_start),
            "end": fields.Date.to_string(task.agile_planned_end or task.agile_planned_start),
            "status": task.agile_status, "late": task.id in late_ids, "circular": task.id in circular,
            **self._release(task),
            **(info or {}).get(task.id, {"blocked_by": [], "collision": None}),
        }

    @api.model
    def _release(self, task):
        """The release of an item, for colouring bars by release."""
        release = task.sudo().version_id
        return {"release_id": release.id or False, "release": release.name or ""}

    @api.model
    def _epic_row(self, epic, kids, late_ids, circular, epics_only, info=None):
        """An epic bar from its own dates, or the span of its dated children; None when it has neither."""
        kid_rows = [self._issue_row(t, late_ids, circular, info) for t in kids.sorted("agile_planned_start")]
        start = epic.agile_planned_start and fields.Date.to_string(epic.agile_planned_start)
        end = epic.agile_planned_end and fields.Date.to_string(epic.agile_planned_end)
        if kid_rows:
            start = start or min(r["start"] for r in kid_rows)
            end = end or max(r["end"] for r in kid_rows)
        derived = False
        if not start:
            # No dates of its own or on its issues: follow the sprints its issues are in (NU-53).
            sprints = self.env["project.task"].search([
                ("parent_id", "=", epic.id), ("agile_issue", "=", True), ("sprint_id", "!=", False),
            ]).sprint_id.filtered("date_start")
            if sprints:
                start = fields.Date.to_string(min(sprints.mapped("date_start")))
                end = fields.Date.to_string(max(sprints.mapped("date_end")))
                derived = True
        if not start:
            return None
        return {
            "derived": derived,
            "kind": "epic", "id": epic.id, "key": epic.issue_key or "", "name": epic.name,
            "start": start, "end": max(end or start, start), "status": epic.agile_status,
            "done": epic.agile_child_done_count, "total": epic.agile_child_issue_count,
            "late": epic.id in late_ids or any(r["late"] for r in kid_rows),
            "circular": epic.id in circular, "children": [] if epics_only else kid_rows,
            **self._release(epic),
            **(info or {}).get(epic.id, {"blocked_by": [], "collision": None}),
        }

    @api.model
    def _dependencies(self, scheduled, universe):
        """Arrows between scheduled items, the ones the person cannot read as stubs, and items in a loop."""
        readable = self.env["project.task"].search([("id", "in", universe.ids)])
        by_id = {t.id: t for t in scheduled}
        deps, graph = [], {}
        for task in scheduled:
            for blocker in task.sudo().depend_on_ids:
                if not blocker.agile_issue or not blocker.active:
                    continue
                graph.setdefault(task.id, set()).add(blocker.id)
                if blocker.id not in readable.ids and blocker.id not in by_id:
                    deps.append({"from": None, "to": task.id, "late": False, "hidden": True})
                    continue
                source = by_id.get(blocker.id)
                if not source or source.id not in readable.ids:
                    continue
                end = source.agile_planned_end or source.agile_planned_start
                deps.append({
                    "from": source.id, "to": task.id, "hidden": False,
                    # A blocker that is done or canceled never holds up what it blocks.
                    "late": bool(
                        end and task.agile_planned_start and end > task.agile_planned_start
                        and source.agile_status not in DONE_STATUSES
                    ),
                    "from_key": source.issue_key or "", "from_end": fields.Date.to_string(end),
                    "from_project": source.project_id.name, "from_status": source.agile_status,
                })
        return deps, self._in_loop(graph)

    @api.model
    def _collision(self, task, blockers):
        """The open blocker that ends last, when it ends after the task starts.

        Gives the days of overlap and the earliest valid start (the day after that end). Moving the
        start keeps the task's length, so its end moves by the same number of days.
        """
        start = task.agile_planned_start
        dated = [
            (b.agile_planned_end or b.agile_planned_start, b) for b in blockers
            if b.agile_status not in DONE_STATUSES and (b.agile_planned_end or b.agile_planned_start)
        ]
        if not start or not dated:
            return None
        end, blocker = max(dated, key=lambda pair: pair[0])
        if end <= start:
            return None
        earliest = end + timedelta(days=1)
        task_end = task.agile_planned_end
        return {
            "blocker_id": blocker.id, "blocker_key": blocker.issue_key or "", "blocker_end": fields.Date.to_string(end),
            "days": (end - start).days, "earliest_start": fields.Date.to_string(earliest),
            "new_end": fields.Date.to_string(task_end + (earliest - start)) if task_end else None,
        }

    @api.model
    def _row_info(self, deps, by_id):
        """For each blocked item: its open blockers and the collision with the one that ends last."""
        grouped = {}
        for dep in deps:
            if dep["hidden"] or dep["from_status"] in DONE_STATUSES:
                continue
            grouped.setdefault(dep["to"], []).append(dep)
        info = {}
        for to_id, entries in grouped.items():
            info[to_id] = {
                "blocked_by": [
                    {"key": e["from_key"], "end": e["from_end"], "project": e["from_project"]}
                    for e in sorted(entries, key=lambda e: e["from_key"])
                ],
                "collision": self._collision(by_id[to_id], [by_id[e["from"]] for e in entries]),
            }
        return info

    @api.model
    def _in_loop(self, graph):
        """Ids that can reach themselves by following blocked-by links."""
        found = set()
        for start in graph:
            stack, seen = list(graph[start]), set()
            while stack:
                node = stack.pop()
                if node == start:
                    found.add(start)
                    break
                if node in seen:
                    continue
                seen.add(node)
                stack.extend(graph.get(node, ()))
        return found

    # ---- Blockers of one issue (P-921): the Roadmap panel lists, adds and removes them ----

    @api.model
    def _blocker_task(self, task_id):
        task = self.env["project.task"].browse(task_id).exists()
        if not task or not task.agile_issue:
            raise UserError(_("Blockers are available for Agile issues only."))
        task.check_access("read")
        return task

    @api.model
    def _transitive(self, task, field_name):
        """Every issue reached by following one link field again and again."""
        found, stack = set(), list(task.sudo()[field_name])
        while stack:
            node = stack.pop()
            if node.id in found:
                continue
            found.add(node.id)
            stack.extend(node[field_name])
        return found

    @api.model
    def _blocker_sentence(self, task, blocker):
        end = blocker.agile_planned_end or blocker.agile_planned_start
        if not end:
            return _("Blocked by %(key)s, which has no planned dates.", key=blocker.issue_key)
        start = task.agile_planned_start
        if start and end > start:
            days = (end - start).days
            return _(
                "Blocked by %(key)s, which ends %(end)s, %(days)s days after this starts.",
                key=blocker.issue_key, end=fields.Date.to_string(end), days=days,
            )
        return _("Blocked by %(key)s, which ends %(end)s.", key=blocker.issue_key, end=fields.Date.to_string(end))

    @api.model
    def _blocker_payload(self, task):
        all_blockers = task.sudo().depend_on_ids.filtered(lambda b: b.agile_issue and b.active)
        readable = all_blockers.filtered(lambda b: b.with_user(self.env.user).has_access("read")).with_env(self.env)
        try:
            task._check_agile_issue_link_permission()
            can_edit = True
        except AccessError:
            can_edit = False
        return {
            "id": task.id,
            "key": task.issue_key or "",
            "name": task.name,
            "start": fields.Date.to_string(task.agile_planned_start),
            "can_edit": can_edit,
            "blockers": [
                {
                    "id": b.id, "key": b.issue_key or "", "name": b.name, "project": b.project_id.name,
                    "status": b.agile_status, "end": fields.Date.to_string(b.agile_planned_end or b.agile_planned_start),
                    "sentence": self._blocker_sentence(task, b),
                    "late": bool(
                        (b.agile_planned_end or b.agile_planned_start) and task.agile_planned_start
                        and (b.agile_planned_end or b.agile_planned_start) > task.agile_planned_start
                        and b.agile_status not in DONE_STATUSES
                    ),
                }
                for b in readable.sorted("issue_key")
            ],
            "hidden": len(all_blockers) - len(readable),
            "collision": self._collision(task, readable),
            "can_move": task.project_id._agile_allows("roadmap_dates"),
        }

    @api.model
    def blockers(self, task_id):
        return self._blocker_payload(self._blocker_task(task_id))

    @api.model
    def move_to_earliest_start(self, task_id, expected_start):
        """Move an item's start to the day after its last open blocker ends, keeping its length.

        `expected_start` is the start the person saw; if it changed meanwhile nothing moves.
        The write itself checks that the person may change planned dates.
        """
        task = self._blocker_task(task_id)
        if fields.Date.to_string(task.agile_planned_start) != expected_start:
            raise UserError(_(
                "%(key)s was changed by someone else. Reload the Roadmap and try again. Nothing was changed.",
                key=task.issue_key,
            ))
        all_blockers = task.sudo().depend_on_ids.filtered(lambda b: b.agile_issue and b.active)
        readable = all_blockers.filtered(lambda b: b.with_user(self.env.user).has_access("read")).with_env(self.env)
        collision = self._collision(task, readable)
        if not collision:
            raise UserError(_("Nothing to move: no open blocker ends after %(key)s starts.", key=task.issue_key))
        new_start = fields.Date.to_date(collision["earliest_start"])
        new_end = fields.Date.to_date(collision["new_end"]) if collision["new_end"] else False
        epic = task.parent_id if task.parent_id.agile_is_epic else task.browse()
        if epic and epic.agile_planned_start and epic.agile_planned_end and (
            new_start < epic.agile_planned_start or (new_end or new_start) > epic.agile_planned_end
        ):
            raise UserError(_(
                "Moving %(key)s to %(date)s would take it outside its epic %(epic)s, which runs %(start)s to %(end)s. Change the epic's dates first.",
                key=task.issue_key, date=collision["earliest_start"], epic=epic.issue_key,
                start=fields.Date.to_string(epic.agile_planned_start), end=fields.Date.to_string(epic.agile_planned_end),
            ))
        old = {"start": expected_start, "end": fields.Date.to_string(task.agile_planned_end)}
        task.write({"agile_planned_start": new_start, "agile_planned_end": new_end})
        return {
            "old": old, "new": {"start": collision["earliest_start"], "end": collision["new_end"]},
            "panel": self._blocker_payload(task),
        }

    @api.model
    def undo_move_start(self, task_id, old_start, old_end, new_start):
        """Put the dates back, only if nobody changed the start since the move."""
        task = self._blocker_task(task_id)
        if fields.Date.to_string(task.agile_planned_start) != new_start:
            raise UserError(_("%(key)s was changed after the move, so it was not put back.", key=task.issue_key))
        task.write({"agile_planned_start": old_start or False, "agile_planned_end": old_end or False})
        return self._blocker_payload(task)

    @api.model
    def add_blocker(self, task_id, blocker_id):
        task = self._blocker_task(task_id)
        task._check_agile_issue_link_permission()
        blocker = self.env["project.task"].browse(blocker_id).exists()
        if not blocker or not blocker.agile_issue:
            raise UserError(_("Pick an Agile issue to add as a blocker."))
        blocker.check_access("read")
        if blocker == task:
            raise UserError(_("An issue cannot block itself."))
        if task.id in self._transitive(blocker, "depend_on_ids"):
            raise UserError(_(
                "%(key)s already depends on this issue, directly or through other issues, so it cannot also block it.",
                key=blocker.issue_key,
            ))
        task.write({"depend_on_ids": [(4, blocker.id)]})
        return self._blocker_payload(task)

    @api.model
    def remove_blocker(self, task_id, blocker_id):
        task = self._blocker_task(task_id)
        task._check_agile_issue_link_permission()
        task.write({"depend_on_ids": [(3, blocker_id)]})
        return self._blocker_payload(task)

    @api.model
    def search_blockers(self, task_id, term="", limit=8):
        """Issues the person could add as a blocker: readable, not already linked, and not in a loop."""
        task = self._blocker_task(task_id)
        excluded = {task.id, *task.sudo().depend_on_ids.ids, *self._transitive(task, "dependent_ids")}
        domain = [("agile_issue", "=", True), ("id", "not in", list(excluded)), ("company_id", "=", task.company_id.id)]
        term = (term or "").strip()
        if term:
            domain += ["|", ("name", "ilike", term), ("issue_key", "ilike", term)]
        found = self.env["project.task"].search(domain, order="issue_key", limit=limit)
        return [{"id": t.id, "key": t.issue_key or "", "name": t.name, "project": t.project_id.name} for t in found]

    @api.model
    def late_dependency_count(self, project):
        """Late blocker arrows in one project, for the sidebar badge."""
        Task = self.env["project.task"]
        issues = Task.search([
            ("project_id", "=", project.id), ("agile_issue", "=", True), ("active", "=", True),
            ("agile_planned_start", "!=", False),
        ])
        deps, _loop = self._dependencies(issues, issues)
        return sum(1 for d in deps if d["late"])
