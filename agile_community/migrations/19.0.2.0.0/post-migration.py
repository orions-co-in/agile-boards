"""Switch on again the views the pre-migration switched off that stay in agile_community."""
PARAM = "agile_community.split_deactivated_views"


def migrate(cr, version):
    if not version:
        return
    cr.execute("SELECT value FROM ir_config_parameter WHERE key = %s", (PARAM,))
    row = cr.fetchone()
    ids = [int(i) for i in (row[0] or "").split(",") if i] if row else []
    if ids:
        cr.execute(
            """UPDATE ir_ui_view SET active = true
                WHERE id = ANY(%s)
                  AND EXISTS (SELECT 1 FROM ir_model_data d
                               WHERE d.model = 'ir.ui.view' AND d.res_id = ir_ui_view.id
                                 AND d.module = 'agile_community')""",
            (ids,),
        )
    cr.execute("DELETE FROM ir_config_parameter WHERE key = %s", (PARAM,))
