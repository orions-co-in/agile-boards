from odoo import Command, SUPERUSER_ID, api


def migrate(cr, version):
    """Make seeded issue types defaults, not upgrade-time policy overrides."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    cr.execute(
        """
        UPDATE ir_model_data
           SET noupdate = TRUE
         WHERE module = 'agile_community'
           AND name IN (
               'agile_task_type_epic',
               'agile_task_type_story',
               'agile_task_type_task',
               'agile_task_type_bug'
           )
        """
    )
    # Earlier releases could remove an existing task's stage/project link while
    # enabling Agile. Restore links for still-native tasks without changing their
    # stage or native status. Global stages remain global.
    native_tasks = env["project.task"].search([
        ("project_id.agile_enabled", "=", True),
        ("agile_issue", "=", False),
        ("stage_id", "!=", False),
    ])
    for task in native_tasks:
        stage = task.stage_id
        if (
            not stage.agile_status
            and stage.project_ids
            and task.project_id not in stage.project_ids
        ):
            stage.write({"project_ids": [Command.link(task.project_id.id)]})
