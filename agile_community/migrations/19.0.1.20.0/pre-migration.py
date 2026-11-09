def migrate(cr, version):
    """Allow the updated project-scoped metric and release rules to load."""
    cr.execute(
        """
        UPDATE ir_model_data
           SET noupdate = FALSE
         WHERE module = 'agile_community'
           AND name IN (
                'agile_metric_snapshot_project_user_rule',
                'agile_metric_snapshot_company_rule',
                'agile_metric_snapshot_manager_rule',
                'agile_metric_line_project_user_rule',
                'agile_metric_line_company_rule',
                'agile_metric_line_manager_rule',
                'agile_metric_event_project_user_rule',
                'agile_metric_event_company_rule',
                'agile_metric_event_manager_rule',
                'agile_project_version_visibility_rule',
                'agile_project_version_manager_rule',
                'agile_release_audit_visibility_rule',
                'agile_release_audit_manager_rule'
           )
        """
    )
