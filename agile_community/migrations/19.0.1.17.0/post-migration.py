from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env["agile.metric.snapshot"]._cron_capture_daily_snapshots()
