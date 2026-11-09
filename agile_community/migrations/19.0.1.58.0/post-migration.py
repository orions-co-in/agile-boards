def migrate(cr, version):
    """Links gained a direction column and a Clones type; old rows keep their neutral wording.

    The ORM adds `source_id` on upgrade; this only makes sure the column exists when the
    migration runs first, so no old duplicate row is given a direction it never had.
    """
    cr.execute("ALTER TABLE agile_community_issue_link ADD COLUMN IF NOT EXISTS source_id integer")
