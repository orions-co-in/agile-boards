def migrate(cr, version):
    """Initialize the new project timezone field for existing Odoo projects."""
    cr.execute(
        """
        UPDATE project_project
           SET agile_timezone = 'UTC'
         WHERE agile_timezone IS NULL OR agile_timezone = ''
        """
    )
