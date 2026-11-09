from psycopg2 import IntegrityError

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestAgileProjectSetup(TransactionCase):
    def test_extends_project_without_separate_app_menu(self):
        self.assertFalse(self.env.ref("agile_community.agile_root_menu").active)
        self.assertFalse(self.env.ref("agile_community.agile_projects_menu").active)
        self.assertEqual(
            self.env.ref("agile_community.agile_project_settings_inherit").inherit_id,
            self.env.ref("project.edit_project"),
        )

    def test_create_agile_project_and_keep_native_project_independent(self):
        native = self.env["project.project"].create({"name": "Native"})
        agile = self.env["project.project"].create({
            "name": "Website", "agile_enabled": True,
            "agile_key": " web ", "agile_method": "scrum",
        })
        self.assertFalse(native.agile_enabled)
        self.assertEqual(agile.agile_key, "WEB")
        self.assertEqual(agile.agile_method, "scrum")

    def test_duplicate_and_invalid_keys_are_rejected(self):
        self.env["project.project"].create({
            "name": "First", "agile_enabled": True, "agile_key": "FIR",
        })
        with self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self.env["project.project"].create({
                    "name": "Duplicate", "agile_enabled": True, "agile_key": "fir",
                })
        with self.assertRaises(ValidationError):
            self.env["project.project"].create({
                "name": "Invalid", "agile_enabled": True, "agile_key": "1BAD",
            })
