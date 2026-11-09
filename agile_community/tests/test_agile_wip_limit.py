from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user


class TestAgileProjectWipLimit(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(
            cls.env,
            login="agile_wip_manager",
            groups="project.group_project_manager",
        )
        cls.contributor = new_test_user(
            cls.env,
            login="agile_wip_contributor",
            groups="project.group_project_user",
        )
        cls.project = cls.env["project.project"].with_user(cls.manager).create({
            "name": "WIP limits",
            "privacy_visibility": "employees",
            "agile_enabled": True,
            "agile_key": "WIP",
        })
        cls.stages = {
            stage.agile_status: stage
            for stage in cls.project.type_ids.filtered("agile_status")
        }
        cls.limit_model = cls.env["agile.project.wip.limit"]

    def test_project_manager_can_configure_only_active_project_stages(self):
        limit = self.limit_model.with_user(self.manager).create({
            "project_id": self.project.id,
            "stage_id": self.stages["progress"].id,
            "wip_limit": 3,
        })
        self.assertEqual(limit.wip_limit, 3)

        with self.assertRaises(ValidationError):
            self.limit_model.with_user(self.manager).create({
                "project_id": self.project.id,
                "stage_id": self.stages["done"].id,
                "wip_limit": 2,
            })
        with self.assertRaises(ValidationError):
            limit.with_user(self.manager).write({"wip_limit": 0})

    def test_a_limit_can_count_per_swimlane_row(self):
        limit = self.limit_model.with_user(self.manager).create({
            "project_id": self.project.id,
            "stage_id": self.stages["progress"].id,
            "wip_limit": 2,
        })
        entry = self.project.with_user(self.manager).agile_board_wip()["stages"][0]
        self.assertFalse(entry["per_swimlane"])
        limit.with_user(self.manager).write({"per_swimlane": True})
        entry = self.project.with_user(self.manager).agile_board_wip()["stages"][0]
        self.assertTrue(entry["per_swimlane"])
        self.assertEqual(entry["limit"], 2)
        with self.assertRaises(AccessError):
            limit.with_user(self.contributor).write({"per_swimlane": False})

    def test_non_manager_cannot_change_wip_limit(self):
        limit = self.limit_model.with_user(self.manager).create({
            "project_id": self.project.id,
            "stage_id": self.stages["ready"].id,
            "wip_limit": 2,
        })
        with self.assertRaises(AccessError):
            limit.with_user(self.contributor).write({"wip_limit": 5})
        self.assertEqual(limit.wip_limit, 2)

    def test_wip_counts_come_from_an_rpc_and_titles_stay_plain(self):
        self.limit_model.with_user(self.manager).create({
            "project_id": self.project.id,
            "stage_id": self.stages["progress"].id,
            "wip_limit": 1,
        })
        task = self.env["project.task"].with_user(self.manager).create({
            "name": "WIP issue",
            "project_id": self.project.id,
            "user_ids": [(4, self.manager.id)],
        })
        task.with_user(self.manager).action_agile_mark_ready()
        task.with_user(self.manager).action_agile_start()
        additional_task = self.env["project.task"].with_user(self.manager).create({
            "name": "Over-limit WIP issue",
            "project_id": self.project.id,
            "user_ids": [(4, self.manager.id)],
        })
        additional_task.with_user(self.manager).action_agile_mark_ready()
        additional_task.with_user(self.manager).action_agile_start()

        wip = self.project.with_user(self.manager).agile_board_wip()
        self.assertEqual(
            wip["stages"],
            [{"stage_id": self.stages["progress"].id, "limit": 1, "current": 2, "per_swimlane": False}],
        )
        # Column titles stay plain; the board draws the badge from these counts.
        grouped = self.env["project.task"].with_user(self.manager).with_context(
            agile_wip_limit_display=True,
            default_project_id=self.project.id,
        ).web_read_group(
            [("project_id", "=", self.project.id), ("agile_issue", "=", True)],
            ["stage_id"],
            ["__count"],
        )
        self.assertTrue(all("WIP" not in (g["stage_id"] or [0, ""])[1] for g in grouped["groups"]))

        native = self.env["project.project"].create({"name": "Native project"})
        native_stage = self.env["project.task.type"].create({
            "name": "Native work",
            "project_ids": [(4, native.id)],
        })
        native_task = self.env["project.task"].create({
            "name": "Native task",
            "project_id": native.id,
            "stage_id": native_stage.id,
        })
        native_groups = self.env["project.task"].with_context(
            agile_wip_limit_display=True,
            default_project_id=native.id,
        ).web_read_group(
            [("id", "=", native_task.id)], ["stage_id"], ["__count"]
        )
        self.assertTrue(native_groups["groups"])
        native_stage_labels = [
            group["stage_id"][1]
            for group in native_groups["groups"]
            if group["stage_id"]
        ]
        self.assertIn("Native work", native_stage_labels)
        self.assertTrue(all("WIP" not in label for label in native_stage_labels))

    def test_wip_counts_are_for_members_and_skip_unlimited_stages(self):
        self.assertEqual(self.project.with_user(self.manager).agile_board_wip()["stages"], [])
        outsider = new_test_user(self.env, login="agile_wip_outsider", groups="project.group_project_user")
        self.project.write({"privacy_visibility": "followers"})
        with self.assertRaises(AccessError):
            self.project.with_user(outsider).agile_board_wip()
