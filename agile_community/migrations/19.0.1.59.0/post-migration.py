def migrate(cr, version):
    """Rules gained a schedule and three triggers; a scheduled rule needs its start point.

    The ORM adds the new columns on upgrade. Scheduled rules cannot exist before this version,
    so nothing is converted; this only makes sure the columns exist if the migration runs first.
    """
    cr.execute("ALTER TABLE agile_automation_rule ADD COLUMN IF NOT EXISTS last_slot timestamp")
