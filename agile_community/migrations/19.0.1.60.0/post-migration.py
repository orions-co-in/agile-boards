def migrate(cr, version):
    """Rules gained an Otherwise branch: a column that points at the rule an action belongs to.

    The ORM adds it on upgrade; this only makes sure it exists if the migration runs first.
    Existing rules are not Otherwise actions, so the column stays empty for them.
    """
    cr.execute("ALTER TABLE agile_automation_rule ADD COLUMN IF NOT EXISTS otherwise_of_id integer")
