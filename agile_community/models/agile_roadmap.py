from odoo import _, api, fields, models
from odoo.exceptions import AccessError


class AgileRoadmapItem(models.Model):
    """Read-only unified projection of Agile issues, sprints, and releases."""

    _name = "agile.roadmap.item"
    _description = "Agile Roadmap Item"
    _auto = False
    _rec_name = "name"
    _order = "date_start, item_type, name"

    name = fields.Char(readonly=True)
    project_id = fields.Many2one("project.project", readonly=True)
    company_id = fields.Many2one("res.company", readonly=True)
    item_type = fields.Selection(
        [("issue", "Issue"), ("sprint", "Sprint"), ("release", "Release")],
        readonly=True,
    )
    source_id = fields.Integer(readonly=True)
    issue_id = fields.Many2one("project.task", readonly=True)
    sprint_id = fields.Many2one("project.sprint", readonly=True)
    release_id = fields.Many2one("project.version", readonly=True)
    date_start = fields.Date(readonly=True)
    date_end = fields.Date(readonly=True)
    issue_key = fields.Char(readonly=True)
    agile_status = fields.Selection(
        [
            ("backlog", "Backlog"),
            ("ready", "To Do"),
            ("progress", "In Progress"),
            ("review", "Review"),
            ("done", "Done"),
            ("canceled", "Canceled"),
        ],
        readonly=True,
    )
    agile_is_epic = fields.Boolean(readonly=True)
    is_derived = fields.Boolean(
        readonly=True, help="The dates come from the epic's child issues and sprints, because none were typed.",
    )
    child_issue_count = fields.Integer(compute="_compute_issue_progress")
    child_done_count = fields.Integer(compute="_compute_issue_progress")
    dependency_item_ids = fields.Many2many(
        "agile.roadmap.item", compute="_compute_dependency_items"
    )

    def init(self):
        self.env.cr.execute(
            """
            CREATE OR REPLACE VIEW agile_roadmap_item AS (
                SELECT
                    task.id::bigint * 10 + 1 AS id,
                    task.project_id,
                    project.company_id,
                    'issue'::varchar AS item_type,
                    task.id AS source_id,
                    task.id AS issue_id,
                    NULL::integer AS sprint_id,
                    NULL::integer AS release_id,
                    COALESCE(task.agile_planned_start, derived.d_start) AS date_start,
                    CASE WHEN task.agile_planned_start IS NULL THEN derived.d_end
                         ELSE task.agile_planned_end END AS date_end,
                    task.name,
                    task.issue_key,
                    stage.agile_status,
                    issue_type.is_epic AS agile_is_epic,
                    0 AS child_issue_count,
                    0 AS child_done_count,
                    task.agile_planned_start IS NULL AS is_derived
                FROM project_task task
                JOIN project_project project ON project.id = task.project_id
                LEFT JOIN project_task_type stage ON stage.id = task.stage_id
                LEFT JOIN agile_community_task_type issue_type
                    ON issue_type.id = task.agile_task_type_id
                LEFT JOIN LATERAL (
                    SELECT MIN(COALESCE(child.agile_planned_start, child_sprint.date_start)) AS d_start,
                           MAX(COALESCE(child.agile_planned_end, child_sprint.date_end)) AS d_end
                    FROM project_task child
                    LEFT JOIN project_sprint child_sprint ON child_sprint.id = child.sprint_id
                    WHERE child.parent_id = task.id AND child.active AND child.agile_issue
                ) derived ON issue_type.is_epic
                WHERE project.agile_enabled
                    AND task.agile_issue
                    AND task.active
                    AND (task.agile_planned_start IS NOT NULL OR derived.d_start IS NOT NULL)

                UNION ALL

                SELECT
                    sprint.id::bigint * 10 + 2 AS id,
                    sprint.project_id,
                    project.company_id,
                    'sprint'::varchar AS item_type,
                    sprint.id AS source_id,
                    NULL::integer AS issue_id,
                    sprint.id AS sprint_id,
                    NULL::integer AS release_id,
                    sprint.date_start,
                    sprint.date_end,
                    sprint.name,
                    NULL::varchar AS issue_key,
                    NULL::varchar AS agile_status,
                    FALSE AS agile_is_epic,
                    0 AS child_issue_count,
                    0 AS child_done_count,
                    FALSE AS is_derived
                FROM project_sprint sprint
                JOIN project_project project ON project.id = sprint.project_id
                WHERE project.agile_enabled

                UNION ALL

                SELECT
                    release.id::bigint * 10 + 3 AS id,
                    release.project_id,
                    project.company_id,
                    'release'::varchar AS item_type,
                    release.id AS source_id,
                    NULL::integer AS issue_id,
                    NULL::integer AS sprint_id,
                    release.id AS release_id,
                    release.release_date,
                    release.release_date AS date_end,
                    release.name,
                    NULL::varchar AS issue_key,
                    NULL::varchar AS agile_status,
                    FALSE AS agile_is_epic,
                    0 AS child_issue_count,
                    0 AS child_done_count,
                    FALSE AS is_derived
                FROM project_version release
                JOIN project_project project ON project.id = release.project_id
                WHERE project.agile_enabled
                    AND release.active
                    AND release.release_date IS NOT NULL
            )
            """
        )

    @api.depends("issue_id", "issue_id.depend_on_ids", "issue_id.agile_issue")
    def _compute_dependency_items(self):
        for item in self:
            blockers = item.issue_id.depend_on_ids.filtered(
                lambda task: task.agile_issue
                and task.active
                and task.agile_planned_start
                and task.project_id == item.project_id
            )
            item.dependency_item_ids = self.browse(
                [blocker.id * 10 + 1 for blocker in blockers]
            )

    @api.depends("issue_id", "issue_id.agile_child_issue_count", "issue_id.agile_child_done_count")
    def _compute_issue_progress(self):
        for item in self:
            item.child_issue_count = item.issue_id.agile_child_issue_count
            item.child_done_count = item.issue_id.agile_child_done_count

    def action_open_source(self):
        self.ensure_one()
        # The underlying Project record can be natively readable to someone
        # who is not on the Agile team. Enforce access to the projection row
        # itself before using its source relation, including direct RPC calls.
        self.check_access("read")
        source = {
            "issue": self.issue_id,
            "sprint": self.sprint_id,
            "release": self.release_id,
        }.get(self.item_type)
        if not source or not source.has_access("read"):
            raise AccessError(_("You cannot open this roadmap item."))
        return {
            "type": "ir.actions.act_window",
            "name": source.display_name,
            "res_model": source._name,
            "res_id": source.id,
            "view_mode": "form",
            "target": "current",
        }
