def migrate(cr, version):
    """Every existing Agile stage is the only one of its category in its project: mark it the main one."""
    cr.execute(
        """
        UPDATE project_task_type t
           SET agile_is_main = TRUE
         WHERE t.agile_status IS NOT NULL
           AND t.id IN (
                SELECT DISTINCT ON (rel.project_id, s.agile_status) s.id
                  FROM project_task_type s
                  JOIN project_task_type_rel rel ON rel.type_id = s.id
                 WHERE s.agile_status IS NOT NULL
                 ORDER BY rel.project_id, s.agile_status, s.sequence, s.id
           )
        """
    )
