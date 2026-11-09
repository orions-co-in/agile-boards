def migrate(cr, version):
    """Kanban projects can switch the Backlog column on or off (R-1105).

    They already showed it, so existing Kanban projects keep it on; new ones start with it off.
    """
    cr.execute("ALTER TABLE project_project ADD COLUMN IF NOT EXISTS agile_kanban_backlog_column boolean")
    cr.execute(
        """
        UPDATE project_project
           SET agile_kanban_backlog_column = TRUE
         WHERE agile_kanban_backlog_column IS NULL
           AND agile_enabled AND agile_method = 'kanban'
        """
    )
