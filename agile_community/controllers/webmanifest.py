import json

from odoo import _
from odoo.addons.web.controllers.webmanifest import WebManifest
from odoo.http import request, route

AGILE_APP_ID = "agile_community"
AGILE_START_PATH = "odoo/agile-my-work"


class AgileWebManifest(WebManifest):
    """Lets people install Agile on a phone: its own name, icon and start page (R-953)."""

    def _get_scoped_app_name(self, app_id):
        if app_id == AGILE_APP_ID:
            return _("Agile")
        return super()._get_scoped_app_name(app_id)

    def _get_scoped_app_shortcuts(self, app_id):
        shortcuts = super()._get_scoped_app_shortcuts(app_id)
        if app_id == AGILE_APP_ID:
            shortcuts = shortcuts + [{
                "name": _("My work"),
                "url": f"/{AGILE_START_PATH}",
                "icons": self._get_scoped_app_icons(app_id),
            }]
        return shortcuts

    @route()
    def scoped_app_manifest(self, app_id, path, app_name=""):
        response = super().scoped_app_manifest(app_id, path, app_name=app_name)
        if app_id != AGILE_APP_ID:
            return response
        # Odoo scopes an installed app to its start page; Agile spans many pages (Board, Backlog,
        # Reports), so the whole web client is in scope or each move would leave the app window.
        manifest = json.loads(response.get_data(as_text=True))
        manifest["scope"] = "/odoo"
        return request.make_json_response(manifest, {"Content-Type": "application/manifest+json"})
