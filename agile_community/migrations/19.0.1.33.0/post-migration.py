from dateutil.relativedelta import relativedelta

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Sprints whose end date disagrees with their length become custom sprints."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    for sprint in env["project.sprint"].search([("date_option", "!=", "custom")]):
        number, unit = sprint.date_option.split("_")
        if sprint.date_end != sprint.date_start + relativedelta(**{unit: int(number)}):
            cr.execute(
                "UPDATE project_sprint SET date_option = 'custom' WHERE id = %s",
                (sprint.id,),
            )
    env.invalidate_all()
