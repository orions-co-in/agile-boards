from datetime import timedelta

from odoo import _, fields, models

PULSE_MAX_DAYS = 21
PULSE_ON_PACE_TOLERANCE = 1.0
METRIC_FILTERS = ("open", "blocked", "overdue", "review")


def _iso(value):
    return value.isoformat() if value else False


def build_pulse_days(date_start, date_end, today, committed, snapshots):
    """Return one dict per displayed sprint day.

    ``snapshots`` maps a date to ``(points_left, scope_points_total, scope_changed)``.
    The ideal line falls straight from ``committed`` on the first working day
    to 0 on the last one and stays flat over weekends.
    """
    total_days = (date_end - date_start).days + 1
    all_days = [date_start + timedelta(days=n) for n in range(total_days)]
    working = [day for day in all_days if day.weekday() < 5]
    last_step = max(len(working) - 1, 1)

    def ideal_for(day):
        steps_done = len([w for w in working if w < day])
        if day.weekday() >= 5 and steps_done:
            steps_done -= 1  # weekend cells repeat the last working day
        if len(working) <= 1:
            return float(committed)
        return round(committed * (1 - steps_done / last_step), 2)

    if total_days > PULSE_MAX_DAYS:
        anchor = min(max(today, date_start), date_end)
        first = max(date_start, min(anchor - timedelta(days=10), date_end - timedelta(days=PULSE_MAX_DAYS - 1)))
        window = [first + timedelta(days=n) for n in range(PULSE_MAX_DAYS)]
    else:
        window = all_days

    days = []
    last_known = None
    previous_scope = None
    for day in all_days:
        snap = snapshots.get(day)
        if day > today:
            left, estimated = None, False
        elif snap:
            left, estimated = snap[0], False
            last_known = left
        else:
            left, estimated = last_known, last_known is not None
        scope_points = 0.0
        if snap and day <= today:
            if previous_scope is not None and snap[2]:
                scope_points = round(snap[1] - previous_scope, 2)
            previous_scope = snap[1]
        if day in window:
            days.append({
                "date": _iso(day),
                "day_number": (day - date_start).days + 1,
                "is_weekend": day.weekday() >= 5,
                "is_today": day == today,
                "is_future": day > today,
                "points_left": left,
                "estimated": estimated,
                "ideal_left": ideal_for(day),
                "scope_changed": scope_points != 0,
                "scope_points": scope_points,
            })
    return days


def pace_for(points_left, ideal_left):
    if points_left is None:
        return None
    delta = round(points_left - ideal_left, 2)
    if abs(delta) <= PULSE_ON_PACE_TOLERANCE:
        status = "on_pace"
    else:
        status = "behind" if delta > 0 else "ahead"
    return {
        "points_left": points_left,
        "ideal_left": ideal_left,
        "delta": delta,
        "status": status,
    }


class ProjectProject(models.Model):
    _inherit = "project.project"

    def _agile_metric_domain(self, metric):
        """Domain shared by the Overview counts and their drill-down lists."""
        self.ensure_one()
        domain = [
            ("project_id", "=", self.id),
            ("agile_issue", "=", True),
            ("active", "=", True),
            ("agile_is_epic", "=", False),
            ("child_ids", "=", False),
        ]
        not_closed = ("stage_id.agile_status", "not in", ["done", "canceled"])
        if metric == "blocked":
            domain += [("agile_is_blocked", "=", True), not_closed]
        elif metric == "overdue":
            utc_midnight = self._agile_local_day_start_utc()
            domain += [
                ("date_deadline", "<", fields.Datetime.to_string(utc_midnight)),
                not_closed,
            ]
        elif metric == "review":
            domain += [("stage_id.agile_status", "=", "review")]
        elif metric == "unassigned":
            domain += [("user_ids", "=", False), not_closed]
        elif metric == "unestimated":
            domain += [("story_points_estimated", "=", False), not_closed]
            if self.scrum_estimate_unit == "issues":
                domain += [("id", "=", False)]  # Issue count: every issue is estimated
        else:
            domain += [not_closed]
        return domain

    def action_open_agile_overview(self):
        self.ensure_one()
        self._check_agile_metrics_access()
        return {
            "type": "ir.actions.client",
            "tag": "agile_community.overview",
            "name": _("Overview"),
            "params": {"project_id": self.id},
            # Kept in the breadcrumb: params are lost when the page is reopened with the Back button.
            "context": {"active_id": self.id, "default_project_id": self.id},
        }

    def _agile_active_sprints(self):
        """Active sprints of this project, earliest start first (several when the project allows it)."""
        self.ensure_one()
        return self.env["project.sprint"].search(
            [("project_id", "=", self.id), ("state", "=", "in_progress")],
            order="date_start, id",
        )

    def agile_pulse_data(self, sprint_id=None):
        """Data for the Agile Overview: sprint pulse strip and issue counts.

        With several active sprints, ``sprint_id`` picks the one the pulse follows.
        """
        self.ensure_one()
        self._check_agile_metrics_access()
        task_model = self.env["project.task"]
        counts = {
            metric: task_model.search_count(self._agile_metric_domain(metric))
            for metric in METRIC_FILTERS
        }
        data = {
            "today": _iso(fields.Date.context_today(self)),
            "project": {"id": self.id, "name": self.display_name},
            "estimate_unit": self.scrum_estimate_unit,
            "counts": counts,
            "state": "none",
            "sprint": False,
            "days": [],
            "pace": None,
            "scope_changes": [],
            "can_manage": False,
            "can_manage_project": self._agile_role_for_user() == "manager",
        }
        if self.agile_method != "scrum":
            data["state"] = "kanban"
            return data

        sprint_model = self.env["project.sprint"]
        domain = [("project_id", "=", self.id)]
        active_sprints = self._agile_active_sprints()
        data["active_sprints"] = [{"id": row.id, "name": row.name} for row in active_sprints]
        sprint = active_sprints.filtered(lambda row: row.id == sprint_id)[:1] or active_sprints[:1]
        state = "active"
        if not sprint:
            sprint = sprint_model.search(
                domain + [("state", "=", "draft")], order="date_start, id", limit=1
            )
            state = "planned"
        if not sprint:
            sprint = sprint_model.search(
                domain + [("state", "=", "done")], order="date_end desc, id desc", limit=1
            )
            state = "completed"
        if not sprint:
            return data

        today = fields.Date.context_today(self)
        committed = (
            sprint.committed_points_at_close
            if sprint.state == "done"
            else sprint.planned_points
        )
        data["can_manage"] = bool(sprint.can_manage_project_sprint)
        data["sprint"] = {
            "id": sprint.id,
            "name": sprint.name,
            "state": sprint.state,
            "date_start": _iso(sprint.date_start),
            "date_end": _iso(sprint.date_end),
            "committed_points": committed,
            "planned_points": sprint.planned_points,
            "capacity_points": sprint.capacity_points,
            "completed_points": sprint.completed_points,
            "total_days": (sprint.date_end - sprint.date_start).days + 1,
        }
        if state == "planned":
            data["state"] = "planned"
            return data

        snapshots = self._agile_sprint_snapshots(sprint)
        if state == "active" and not snapshots:
            data["state"] = "waiting"
            return data

        shown_today = today if state == "active" else sprint.date_end
        days = build_pulse_days(
            sprint.date_start, sprint.date_end, shown_today, committed, snapshots
        )
        data["state"] = state
        data["days"] = days
        data["scope_changes"] = [
            {"date": day["date"], "points_delta": day["scope_points"]}
            for day in days
            if day["scope_changed"]
        ]
        reference = next(
            (d for d in reversed(days) if d["points_left"] is not None and not d["is_future"]),
            None,
        )
        if state == "active" and reference:
            data["pace"] = pace_for(reference["points_left"], reference["ideal_left"])
        return data

    def _agile_sprint_snapshots(self, sprint):
        """Latest snapshot per day: {date: (points_left, scope_points, scope_changed)}."""
        snapshot_model = self.env["agile.metric.snapshot"]
        snapshots = snapshot_model.search(
            [("sprint_id", "=", sprint.id)], order="captured_at, id"
        )
        if not snapshots:
            return {}
        groups = self.env["agile.metric.snapshot.line"]._read_group(
            [("snapshot_id", "in", snapshots.ids)],
            ["snapshot_id"],
            ["remaining_points:sum", "story_points:sum"],
        )
        totals = {snap.id: (left, scope) for snap, left, scope in groups}
        by_day = {}
        for snap in snapshots:  # ascending capture time, so later ones win
            left, scope = totals.get(snap.id, (0.0, 0.0))
            by_day[snap.snapshot_date] = (left, scope, bool(snap.scope_change_count))
        if sprint.state == "in_progress":
            # Work finished since the last capture must show today (NU-02).
            today = fields.Date.context_today(self)
            live_left, live_scope = snapshot_model._live_sprint_totals(sprint)
            last = by_day.get(today) or by_day[max(by_day)]
            changed = bool(by_day.get(today, (0, 0, False))[2]) or live_scope != last[1]
            by_day[today] = (live_left, live_scope, changed)
        return by_day
