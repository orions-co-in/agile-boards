from odoo.tests.common import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestAgileInstallApp(HttpCase):
    def test_installable_app_has_its_own_name_start_page_and_icon(self):
        path = "odoo%2Fagile-my-work"
        page = self.url_open(f"/scoped_app?app_id=agile_community&path={path}&app_name=Agile")
        self.assertEqual(page.status_code, 200)
        manifest = self.url_open(f"/web/manifest.scoped_app_manifest?app_id=agile_community&path=%2F{path}").json()
        self.assertEqual(manifest["name"], "Agile")
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(manifest["scope"], "/odoo", "every Agile page stays inside the app window")
        self.assertEqual(manifest["start_url"], "/odoo/agile-my-work")
        self.assertTrue(manifest["icons"][0]["src"].endswith("agile_community/static/description/icon.svg"))
        self.assertEqual(manifest["shortcuts"][0]["url"], "/odoo/agile-my-work")
        self.assertEqual(self.url_open(manifest["icons"][0]["src"]).status_code, 200)

    def test_install_start_page_is_a_real_action_path(self):
        action = self.env["ir.actions.actions"].search([("path", "=", "agile-my-work")])
        self.assertTrue(action, "the installed app opens on My work")

    def test_module_is_listed_as_an_app_with_a_clear_summary(self):
        # NU first impressions: Apps hides modules that are not applications.
        module = self.env["ir.module.module"].search([("name", "=", "agile_community")])
        self.assertTrue(module.application, "Agile shows under the default Apps filter")
        self.assertIn("Scrum", module.summary)
        self.assertNotIn("settings within", module.summary.lower())
