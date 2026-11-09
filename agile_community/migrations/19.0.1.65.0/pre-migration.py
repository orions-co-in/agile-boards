def migrate(cr, version):
    """Agile record rules update with the module again.

    Six team rules sat in a noupdate block, so the Odoo-administrator escape (RBAC merge) would
    never reach existing databases. Clear the flag on every Agile rule except the issue type
    company rule, which stays noupdate on purpose.
    """
    cr.execute(
        """
        UPDATE ir_model_data
           SET noupdate = FALSE
         WHERE module = 'agile_community'
           AND model = 'ir.rule'
           AND name <> 'agile_task_type_company_rule'
        """
    )
