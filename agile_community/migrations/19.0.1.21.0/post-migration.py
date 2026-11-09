from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    cr.execute(
        """
        UPDATE project_task AS task
           SET agile_issue = TRUE
          FROM project_project AS project
         WHERE task.project_id = project.id
           AND project.agile_enabled IS TRUE
           AND (
                task.issue_key IS NOT NULL
                OR task.agile_task_type_id IS NOT NULL
                OR task.sprint_id IS NOT NULL
                OR task.version_id IS NOT NULL
           )
        """
    )
    # Refresh computed model caches on later ORM reads in this migration.
    env.invalidate_all()
