def migrate(cr, version):
    """Cards now start from the project's defaults (R-1102).

    A person who already changed their card fields or density keeps them: their
    preference is marked as their own choice. Everyone else follows the project.
    """
    cr.execute("ALTER TABLE agile_project_view_preference ADD COLUMN IF NOT EXISTS card_custom boolean")
    cr.execute(
        """
        UPDATE agile_project_view_preference
           SET card_custom = (
               density <> 'comfortable'
               OR NOT show_assignee OR NOT show_issue_type OR NOT show_priority
               OR NOT show_points OR NOT show_component OR show_fix_version
               OR show_tags OR NOT show_deadline
           )
         WHERE card_custom IS NULL
        """
    )
