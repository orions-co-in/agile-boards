import re

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user


class TestAgileIssueIdentity(TransactionCase):
    """F-02: Issue identity and types"""

    def test_key_generated_on_create_for_agile_project(self):
        project = self.env["project.project"].create({
            "name": "Website", "agile_enabled": True,
            "agile_key": "WEB", "agile_method": "scrum",
        })
        task = self.env["project.task"].create({
            "name": "Test issue", "project_id": project.id,
        })
        self.assertTrue(task.issue_key, "Issue key should be auto-generated")
        self.assertTrue(
            re.match(r"^WEB-\d+$", task.issue_key),
            f"Key format invalid: {task.issue_key}",
        )
        self.assertEqual(task.issue_key, "WEB-0001")

    def test_an_issue_type_used_only_by_an_archived_issue_cannot_be_deleted(self):
        """E2E-001: an archived issue still uses the type; the delete says archive instead, not a database error."""
        project = self.env["project.project"].create({
            "name": "Types", "agile_enabled": True, "agile_key": "TYP", "agile_method": "kanban",
        })
        kind = self.env["agile_community.task_type"].create({"name": "Used by a hidden issue", "project_ids": [Command.set(project.ids)]})
        task = self.env["project.task"].create({"name": "Hidden", "project_id": project.id, "agile_task_type_id": kind.id})
        task.active = False
        with self.assertRaisesRegex(ValidationError, "archived instead of deleted"):
            kind.unlink()

    def test_no_key_for_native_project(self):
        project = self.env["project.project"].create({"name": "Native"})
        task = self.env["project.task"].create({
            "name": "Native task", "project_id": project.id,
        })
        self.assertFalse(task.issue_key, "Native tasks should not have keys")

    def test_issue_key_cannot_be_supplied_on_create(self):
        project = self.env["project.project"].create({
            "name": "Imported key must be allocated",
            "agile_enabled": True,
            "agile_key": "AUTO",
        })
        with self.assertRaisesRegex(ValidationError, "allocated automatically"):
            self.env["project.task"].create({
                "name": "Issue with forged key",
                "project_id": project.id,
                "issue_key": "AUTO-9000",
            })

    def test_native_task_cannot_be_marked_as_agile_by_import(self):
        project = self.env["project.project"].create({"name": "Native import"})
        with self.assertRaisesRegex(ValidationError, "Agile-enabled project"):
            self.env["project.task"].create({
                "name": "Forged Agile row",
                "project_id": project.id,
                "agile_issue": True,
            })

    def test_parent_issue_key_resolves_only_same_project_issues(self):
        project = self.env["project.project"].create({
            "name": "Parent import",
            "agile_enabled": True,
            "agile_key": "PAR",
        })
        other_project = self.env["project.project"].create({
            "name": "Other project",
            "agile_enabled": True,
            "agile_key": "OTH",
        })
        parent = self.env["project.task"].create({
            "name": "Parent issue",
            "project_id": project.id,
            "agile_task_type_id": self.env.ref("agile_community.agile_task_type_epic").id,
        })
        child = self.env["project.task"].create({
            "name": "Child issue", "project_id": project.id,
        })
        child.parent_issue_key = parent.issue_key
        self.assertEqual(child.parent_id, parent)
        self.assertEqual(child.parent_issue_key, parent.issue_key)
        with self.assertRaisesRegex(ValidationError, "No accessible active issue"):
            child.parent_issue_key = "MISSING-1"
        foreign_parent = self.env["project.task"].create({
            "name": "Foreign parent", "project_id": other_project.id,
        })
        with self.assertRaisesRegex(ValidationError, "No accessible active issue"):
            child.parent_issue_key = foreign_parent.issue_key

    def test_native_import_updates_existing_issue_by_accessible_key(self):
        project = self.env["project.project"].create({
            "name": "Key-based import",
            "agile_enabled": True,
            "agile_key": "KEYIMP",
        })
        task = self.env["project.task"].create({
            "name": "Before import",
            "project_id": project.id,
        })

        result = self.env["project.task"].load(
            ["issue_key", "name"],
            [[task.issue_key, "Updated by native import"]],
        )

        self.assertEqual(result["ids"], [task.id])
        self.assertFalse(result["messages"])
        self.assertEqual(task.name, "Updated by native import")
        self.assertEqual(task.issue_key, "KEYIMP-0001")

    def test_native_import_rejects_unknown_and_duplicate_issue_keys(self):
        project = self.env["project.project"].create({
            "name": "Key import errors",
            "agile_enabled": True,
            "agile_key": "KEYERR",
        })
        task = self.env["project.task"].create({
            "name": "Keep this title",
            "project_id": project.id,
        })
        task_count = self.env["project.task"].search_count([
            ("project_id", "=", project.id),
            ("agile_issue", "=", True),
        ])

        unknown = self.env["project.task"].load(
            ["issue_key", "name"],
            [["KEYERR-9999", "Must not create"]],
        )
        duplicate = self.env["project.task"].load(
            ["issue_key", "name"],
            [
                [task.issue_key, "First update"],
                [task.issue_key, "Second update"],
            ],
        )

        self.assertFalse(unknown["ids"])
        self.assertEqual(unknown["messages"][0]["field"], "issue_key")
        self.assertFalse(duplicate["ids"])
        self.assertEqual(len(duplicate["messages"]), 2)
        self.assertEqual(task.name, "Keep this title")
        self.assertEqual(
            self.env["project.task"].search_count([
                ("project_id", "=", project.id),
                ("agile_issue", "=", True),
            ]),
            task_count,
        )

    def test_unique_keys_in_batch(self):
        project = self.env["project.project"].create({
            "name": "Web", "agile_enabled": True,
            "agile_key": "WEB2", "agile_method": "scrum",
        })
        keys = set()
        for i in range(5):
            task = self.env["project.task"].create({
                "name": f"Issue {i}", "project_id": project.id,
            })
            self.assertNotIn(task.issue_key, keys)
            keys.add(task.issue_key)
        self.assertEqual(keys, {f"WEB2-{number:04d}" for number in range(1, 6)})

    def test_issue_key_format(self):
        project = self.env["project.project"].create({
            "name": "Web", "agile_enabled": True,
            "agile_key": "WEB", "agile_method": "scrum",
        })
        task = self.env["project.task"].create({
            "name": "Issue", "project_id": project.id,
        })
        self.assertEqual(task.issue_key[:4], "WEB-")
        self.assertTrue(task.issue_key[4:].isdigit())

    def test_default_task_types_loaded(self):
        types = self.env["agile_community.task_type"].search([])
        names = types.mapped("name")
        for expected in ["Epic", "Story", "Task", "Bug"]:
            self.assertIn(expected, names)

    def test_type_deactivated_not_deleted(self):
        epic = self.env["agile_community.task_type"].search([("name", "=", "Epic")])
        epic.active = False
        self.assertFalse(epic.active)
        self.assertTrue(epic.exists())
        # Can be reactivated
        epic.active = True
        self.assertTrue(epic.active)

    def test_task_with_type(self):
        project = self.env["project.project"].create({
            "name": "Web", "agile_enabled": True,
            "agile_key": "WEB", "agile_method": "scrum",
        })
        task_type = self.env["agile_community.task_type"].search(
            [("name", "=", "Bug")], limit=1
        )
        task = self.env["project.task"].create({
            "name": "Bug issue", "project_id": project.id,
            "agile_task_type_id": task_type.id,
        })
        self.assertEqual(task.agile_task_type_id.name, "Bug")

    def test_issue_type_is_required_by_server_and_defaults_to_task(self):
        project = self.env["project.project"].create({
            "name": "Required Type",
            "agile_enabled": True,
            "agile_key": "REQTYPE",
        })
        task = self.env["project.task"].create({
            "name": "Default type",
            "project_id": project.id,
            "agile_task_type_id": False,
        })
        self.assertEqual(
            task.agile_task_type_id,
            self.env.ref("agile_community.agile_task_type_task"),
        )
        with self.assertRaisesRegex(ValidationError, "Select an Issue Type"):
            task.write({"agile_task_type_id": False})

    def test_archived_type_is_kept_for_history_but_cannot_be_assigned(self):
        project = self.env["project.project"].create({
            "name": "Archived Type",
            "agile_enabled": True,
            "agile_key": "ARCTYPE",
        })
        bug = self.env.ref("agile_community.agile_task_type_bug")
        historical = self.env["project.task"].create({
            "name": "Historical bug",
            "project_id": project.id,
            "agile_task_type_id": bug.id,
        })
        bug.active = False
        historical.write({"name": "Historical bug retained"})
        self.assertEqual(historical.agile_task_type_id, bug)
        with self.assertRaisesRegex(ValidationError, "archived"):
            self.env["project.task"].create({
                "name": "New archived bug",
                "project_id": project.id,
                "agile_task_type_id": bug.id,
            })
        with self.assertRaisesRegex(ValidationError, "archived"):
            historical.write({"agile_task_type_id": bug.id})

    def test_project_restricted_type_cannot_leak_to_another_project(self):
        project_a = self.env["project.project"].create({
            "name": "Type Project A",
            "agile_enabled": True,
            "agile_key": "TYPEA",
        })
        project_b = self.env["project.project"].create({
            "name": "Type Project B",
            "agile_enabled": True,
            "agile_key": "TYPEB",
        })
        project_type = self.env["agile_community.task_type"].create({
            "name": "Project A Incident",
            "project_ids": [Command.link(project_a.id)],
        })
        allowed = self.env["project.task"].create({
            "name": "Allowed incident",
            "project_id": project_a.id,
            "agile_task_type_id": project_type.id,
        })
        self.assertEqual(allowed.agile_task_type_id, project_type)
        with self.assertRaisesRegex(ValidationError, "not available"):
            self.env["project.task"].create({
                "name": "Leaked incident",
                "project_id": project_b.id,
                "agile_task_type_id": project_type.id,
            })

    def test_native_task_rejects_explicit_agile_type(self):
        project = self.env["project.project"].create({"name": "Native Type"})
        bug = self.env.ref("agile_community.agile_task_type_bug")
        with self.assertRaisesRegex(ValidationError, "Agile-enabled project"):
            self.env["project.task"].create({
                "name": "Native task with Agile type",
                "project_id": project.id,
                "agile_task_type_id": bug.id,
            })

    def test_import_path_applies_issue_type_rules(self):
        project = self.env["project.project"].create({
            "name": "Imported Issues",
            "agile_enabled": True,
            "agile_key": "IMPORT",
        })
        bug = self.env.ref("agile_community.agile_task_type_bug")
        result = self.env["project.task"].load(
            ["name", "project_id/.id", "agile_task_type_id/.id"],
            [["Imported bug", str(project.id), str(bug.id)]],
        )
        self.assertFalse(result["messages"])
        imported = self.env["project.task"].browse(result["ids"])
        self.assertEqual(imported.agile_task_type_id, bug)
        self.assertTrue(imported.issue_key.startswith("IMPORT-"))

    def test_cannot_move_agile_task_to_another_project(self):
        project_a = self.env["project.project"].create({
            "name": "Project A", "agile_enabled": True,
            "agile_key": "PA", "agile_method": "scrum",
        })
        project_b = self.env["project.project"].create({
            "name": "Project B", "agile_enabled": True,
            "agile_key": "PB", "agile_method": "scrum",
        })
        task = self.env["project.task"].create({
            "name": "Task", "project_id": project_a.id,
        })
        with self.assertRaises(ValidationError):
            task.write({"project_id": project_b.id})

    def test_issue_and_project_keys_are_immutable(self):
        project = self.env["project.project"].create({
            "name": "Web", "agile_enabled": True,
            "agile_key": "IMM", "agile_method": "scrum",
        })
        task = self.env["project.task"].create({
            "name": "Issue", "project_id": project.id,
        })
        with self.assertRaises(ValidationError):
            task.issue_key = "IMM-9999"
        with self.assertRaises(ValidationError):
            project.agile_key = "NEW"

    def test_referenced_type_must_be_archived(self):
        project = self.env["project.project"].create({
            "name": "Web", "agile_enabled": True,
            "agile_key": "ARC", "agile_method": "scrum",
        })
        task = self.env["project.task"].create({
            "name": "Issue", "project_id": project.id,
        })
        with self.assertRaises(ValidationError):
            task.agile_task_type_id.unlink()

    def test_name_search_by_issue_key(self):
        project = self.env["project.project"].create({
            "name": "Web", "agile_enabled": True,
            "agile_key": "WEB", "agile_method": "scrum",
        })
        task = self.env["project.task"].create({
            "name": "Findable", "project_id": project.id,
        })
        found = self.env["project.task"].search([
            ("display_name", "ilike", "WEB-" + task.issue_key.split("-")[1]),
        ])
        self.assertIn(task, found)

    def test_project_search_view_includes_issue_key_and_type(self):
        view = self.env.ref("agile_community.project_task_search_agile")
        self.assertIn("issue_key", view.arch)
        self.assertIn("agile_task_type_id", view.arch)
        for filter_name in (
            "agile_blocked", "agile_overdue", "agile_backlog", "agile_ready",
            "agile_in_progress", "agile_review", "agile_done",
            "agile_canceled",
        ):
            self.assertIn(f'name="{filter_name}"', view.arch)

        search_arch = self.env["project.task"].get_view(
            view_id=view.id, view_type="search"
        )["arch"]
        self.assertIn("('issue_key', 'ilike', self)", search_arch)
        self.assertIn("('name', 'ilike', self)", search_arch)
        for native_filter in (
            'name="agile_group_by_issue_type"',
            'name="sprint_id"',
            'name="version_id"',
            'name="project"',
            'name="user"',
            'name="groupby_priority"',
            'name="tags"',
            'name="stage"',
        ):
            self.assertIn(native_filter, search_arch)

    def test_issue_key_name_search_obeys_private_project_rules(self):
        reviewer = new_test_user(
            self.env,
            login="issue_search_uninvited_reviewer",
            groups="agile_community.group_agile_reviewer",
        )
        private_project = self.env["project.project"].create({
            "name": "Private search project",
            "privacy_visibility": "invited_users",
            "agile_enabled": True,
            "agile_key": "PRIVSEARCH",
            "agile_method": "kanban",
        })
        issue = self.env["project.task"].create({
            "name": "Hidden issue key target",
            "description": "This issue must not leak through key lookup.",
            "project_id": private_project.id,
        })

        results = self.env["project.task"].with_user(reviewer).name_search(
            name=issue.issue_key,
        )

        self.assertFalse(results)

    def test_task_export_obeys_private_project_rules(self):
        reviewer = new_test_user(
            self.env,
            login="issue_export_uninvited_reviewer",
            groups="agile_community.group_agile_reviewer,base.group_allow_export",
        )
        private_project = self.env["project.project"].create({
            "name": "Private export project",
            "privacy_visibility": "invited_users",
            "agile_enabled": True,
            "agile_key": "PRIVEXPORT",
            "agile_method": "kanban",
        })
        issue = self.env["project.task"].create({
            "name": "Hidden export target",
            "description": "This issue must not leak through export.",
            "project_id": private_project.id,
        })

        # The export API receives an explicit selected id, so verify that its
        # field fetch still applies the normal project record rule.
        with self.assertRaises(AccessError):
            self.env["project.task"].with_user(reviewer).browse(issue.id).export_data(
                ["name"]
            )

    def test_issue_type_views_menu_and_badges_are_available(self):
        form = self.env.ref("agile_community.view_project_task_form_agile")
        kanban = self.env.ref("agile_community.project_task_kanban_agile")
        task_list = self.env.ref("agile_community.project_task_list_agile")
        type_list = self.env.ref("agile_community.agile_task_type_list")
        type_form = self.env.ref("agile_community.agile_task_type_form")
        menu = self.env.ref("agile_community.agile_task_type_menu")

        self.assertIn("no_create_edit", form.arch)
        self.assertIn("action_agile_move_backlog_up", form.arch)
        self.assertIn("action_agile_move_backlog_down", form.arch)
        self.assertIn("agile_task_type_color", kanban.arch)
        self.assertIn("widget=\"badge\"", kanban.arch)
        self.assertIn("agile_task_type_color", task_list.arch)
        self.assertIn("project_ids", type_list.arch)
        self.assertIn("web_ribbon", type_form.arch)
        self.assertEqual(menu.parent_id, self.env.ref("project.menu_project_config"))
        self.assertIn(
            self.env.ref("base.group_system"), menu.group_ids
        )

    def test_agile_issues_append_and_keyboard_actions_reorder_backlog(self):
        project = self.env["project.project"].create({
            "name": "Ordered backlog",
            "agile_enabled": True,
            "agile_key": "ORDER",
        })
        first, second, third = self.env["project.task"].create([
            {"name": name, "project_id": project.id}
            for name in ("First", "Second", "Third")
        ])
        self.assertEqual([first.sequence, second.sequence, third.sequence], [10, 20, 30])

        second.action_agile_move_backlog_up()
        ordered = self.env["project.task"].search([
            ("project_id", "=", project.id),
            ("stage_id.agile_status", "=", "backlog"),
        ], order="sequence, id")
        self.assertEqual(ordered, second | first | third)
        self.assertEqual(ordered.mapped("sequence"), [10, 20, 30])
        rank_notes = (first | second | third).message_ids.filtered(
            lambda message: "Backlog rank changed" in (message.body or "")
        )
        self.assertEqual(len(rank_notes), 2)
        self.assertTrue(
            all(note.subtype_id == self.env.ref("mail.mt_note") for note in rank_notes)
        )
        self.assertTrue(
            all(note.author_id == self.env.user.partner_id for note in rank_notes)
        )
        self.assertTrue(all(note.date for note in rank_notes))

        second.action_agile_move_backlog_down()
        ordered.invalidate_recordset(["sequence"])
        ordered = ordered.sorted(lambda task: (task.sequence, task.id))
        self.assertEqual(ordered, first | second | third)
        rank_notes = (first | second | third).message_ids.filtered(
            lambda message: "Backlog rank changed" in (message.body or "")
        )
        self.assertEqual(len(rank_notes), 4)

        at_start = first.action_agile_move_backlog_up()
        self.assertEqual(at_start["tag"], "display_notification")
        rank_notes_after_noop = (first | second | third).message_ids.filtered(
            lambda message: "Backlog rank changed" in (message.body or "")
        )
        self.assertEqual(rank_notes_after_noop, rank_notes)
        self.assertEqual(
            self.env["project.task"].search([
                ("project_id", "=", project.id),
                ("stage_id.agile_status", "=", "backlog"),
            ], order="sequence, id"),
            first | second | third,
        )

        native_project = self.env["project.project"].create({
            "name": "Native ordering audit",
        })
        native_task = self.env["project.task"].create({
            "name": "Native task",
            "project_id": native_project.id,
        })
        native_task.write({"sequence": native_task.sequence + 1})
        self.assertFalse(
            native_task.message_ids.filtered(
                lambda message: "Backlog rank changed" in (message.body or "")
            )
        )

    def test_agile_project_action_uses_ranked_views_without_changing_native_projects(self):
        agile_project = self.env["project.project"].create({
            "name": "Ranked Project",
            "agile_enabled": True,
            "agile_key": "RANKED",
        })
        native_project = self.env["project.project"].create({"name": "Native Ordering"})
        agile_views = {
            view_type: view_id
            for view_id, view_type in agile_project.action_view_tasks()["views"]
        }
        native_views = {
            view_type: view_id
            for view_id, view_type in native_project.action_view_tasks()["views"]
        }
        self.assertEqual(
            agile_views["kanban"],
            self.env.ref(
                "agile_community.project_task_kanban_agile_backlog_order"
            ).id,
        )
        self.assertEqual(
            agile_views["list"],
            self.env.ref(
                "agile_community.project_task_list_agile_backlog_order"
            ).id,
        )
        self.assertEqual(
            agile_project.action_view_tasks()["search_view_id"],
            self.env.ref("agile_community.project_task_search_agile").id,
        )
        agile_help = self.env["project.task"].with_context(
            default_project_id=agile_project.id
        ).get_empty_list_help("native Project help")
        # The project's own manager is told how to start, not to ask for access (NU-43).
        self.assertIn("No issues yet", agile_help)
        self.assertIn("<strong>Backlog</strong>", agile_help)
        unconverted = self.env["project.task"].with_context(
            default_project_id=agile_project.id, agile_unconverted_list=True
        ).get_empty_list_help("native Project help")
        self.assertIn("Nothing to convert", unconverted)
        outsider = self.env["res.users"].create({
            "name": "Help outsider", "login": "help_outsider",
            "group_ids": [(6, 0, [self.env.ref("project.group_project_user").id])],
        })
        member_help = self.env["project.task"].with_user(outsider).with_context(
            default_project_id=agile_project.id
        ).get_empty_list_help("native Project help")
        self.assertIn("You are not on this project's Agile team", member_help)
        self.assertIn("Existing Project tasks stay unchanged", member_help)
        self.assertIn("Team and roles", member_help)
        self.assertEqual(
            self.env["project.task"].with_context(
                default_project_id=native_project.id
            ).get_empty_list_help("native Project help"),
            "native Project help",
        )
        self.assertIn("search_view_id", native_project.action_view_tasks())
        self.assertNotEqual(
            native_project.action_view_tasks().get("search_view_id"),
            self.env.ref("agile_community.project_task_search_agile").id,
        )
        self.assertNotIn(
            self.env.ref(
                "agile_community.project_task_kanban_agile_backlog_order"
            ).id,
            native_views.values(),
        )

    def test_only_managers_and_contributors_can_reorder_backlog(self):
        project = self.env["project.project"].create({
            "name": "Restricted reorder",
            "agile_enabled": True,
            "agile_key": "REORDER",
        })
        issue = self.env["project.task"].create({
            "name": "Issue",
            "project_id": project.id,
        })
        stakeholder = new_test_user(
            self.env,
            login="agile_backlog_stakeholder",
            groups="base.group_user,project.group_project_user,agile_community.group_agile_stakeholder",
        )
        with self.assertRaises(AccessError):
            issue.with_user(stakeholder).action_agile_move_backlog_down()

    def test_issue_type_access_by_project_role(self):
        contributor = new_test_user(
            self.env, login="agile_contributor", groups="project.group_project_user"
        )
        manager = new_test_user(
            self.env, login="agile_manager", groups="project.group_project_manager"
        )
        portal = new_test_user(
            self.env, login="agile_portal", groups="base.group_portal"
        )
        task_type_model = self.env["agile_community.task_type"]

        self.assertTrue(task_type_model.with_user(contributor).search([], limit=1))
        with self.assertRaises(AccessError):
            task_type_model.with_user(contributor).create({"name": "Contributor Type"})
        with self.assertRaisesRegex(AccessError, "shared globally"):
            task_type_model.with_user(manager).create({"name": "Manager Shared Type"})

        project = self.env["project.project"].create({
            "name": "Manager's Agile Project",
            "user_id": manager.id,
            "agile_enabled": True,
            "agile_key": "TYPEMGR",
        })
        scoped_type = task_type_model.with_user(manager).with_context(
            default_project_ids=[Command.set([project.id])]
        ).create({"name": "Manager Scoped Type"})
        self.assertEqual(scoped_type.project_ids, project)

        shared_type = task_type_model.create({"name": "Administrator Shared Type"})
        with self.assertRaisesRegex(AccessError, "shared globally"):
            shared_type.with_user(manager).write({"description": "Not allowed"})

        other_project = self.env["project.project"].create({
            "name": "Another Agile Project",
            "agile_enabled": True,
            "agile_key": "TYPEOTHER",
        })
        with self.assertRaisesRegex(AccessError, "Agile Manager"):
            scoped_type.with_user(manager).write({
                "project_ids": [Command.set([project.id, other_project.id])],
            })

        shared_type = task_type_model.create({
            "name": "Shared Across Agile Projects",
            "project_ids": [Command.set([project.id, other_project.id])],
        })
        with self.assertRaisesRegex(AccessError, "Agile Manager"):
            shared_type.with_user(manager).write({
                "project_ids": [Command.set([project.id])],
                "description": "Attempt to edit while detaching the other project",
            })
        self.assertEqual(
            set(shared_type.project_ids.ids), {project.id, other_project.id}
        )
        with self.assertRaises(AccessError):
            task_type_model.with_user(portal).search([])
