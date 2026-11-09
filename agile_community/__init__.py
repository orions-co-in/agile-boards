from . import models
from . import wizard
from . import controllers


def post_init_hook(env):
    env["agile.metric.snapshot"].sudo()._cron_capture_daily_snapshots()
