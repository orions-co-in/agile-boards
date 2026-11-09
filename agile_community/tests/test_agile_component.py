from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user


class TestAgileProjectComponent(TransactionCase):
    def setUp(self):
        super().setUp()
        self.project = self.env["project.project"].create({
            "name": "Component project",
            "agile_enabled": True,
            "agile_key": "COMP",
        })
        self.other_project = self.env["project.project"].create({
            "name": "Other component project",
            "agile_enabled": True,
            "agile_key": "COMP2",
        })
        self.component_model = self.env["agile.project.component"]

    def test_component_assignment_and_fix_version_are_same_project(self):
        component = self.component_model.create({
            "name": "Mobile", "project_id": self.project.id,
        })
        issue = self.env["project.task"].create({
            "name": "Mobile issue",
            "project_id": self.project.id,
            "agile_component_id": component.id,
        })
        self.assertEqual(issue.agile_component_id, component)
        with self.assertRaisesRegex(ValidationError, "same Agile project"):
            issue.write({"agile_component_id": self.component_model.create({
                "name": "Other", "project_id": self.other_project.id,
            }).id})

    def test_archived_component_is_historical_not_reassignable(self):
        component = self.component_model.create({
            "name": "Archived area", "project_id": self.project.id,
        })
        issue = self.env["project.task"].create({
            "name": "Existing issue",
            "project_id": self.project.id,
            "agile_component_id": component.id,
        })
        component.active = False
        issue.write({"name": "Still visible in history"})
        self.assertEqual(issue.agile_component_id, component)
        new_issue = self.env["project.task"].create({
            "name": "New issue", "project_id": self.project.id,
        })
        with self.assertRaisesRegex(ValidationError, "Archived components"):
            new_issue.write({"agile_component_id": component.id})

    def test_referenced_component_cannot_be_deleted(self):
        component = self.component_model.create({
            "name": "Used area", "project_id": self.project.id,
        })
        self.env["project.task"].create({
            "name": "Uses area",
            "project_id": self.project.id,
            "agile_component_id": component.id,
        })
        with self.assertRaisesRegex(UserError, "Archive it instead"):
            component.unlink()

    def test_referenced_component_cannot_be_moved_between_projects(self):
        component = self.component_model.create({
            "name": "Pinned area", "project_id": self.project.id,
        })
        self.env["project.task"].create({
            "name": "Issue with pinned component",
            "project_id": self.project.id,
            "agile_component_id": component.id,
        })

        with self.assertRaisesRegex(UserError, "cannot be moved"):
            component.write({"project_id": self.other_project.id})
        self.assertEqual(component.project_id, self.project)

    def test_project_scoped_manager_can_manage_component_ui_fields(self):
        scoped_manager = new_test_user(
            self.env,
            login="component_project_scoped_manager",
            groups="project.group_project_user",
        )
        project = self.env["project.project"].create({
            "name": "Project-scoped component manager",
            "privacy_visibility": "employees",
            "user_id": scoped_manager.id,
            "agile_enabled": True,
            "agile_key": "COMPMGR",
        })
        component = self.component_model.create({
            "name": "Managed area", "project_id": project.id,
        })
        unassigned_manager = new_test_user(
            self.env,
            login="component_unassigned_project_manager",
            groups="project.group_project_manager",
        )

        self.assertTrue(component.with_user(scoped_manager).can_manage_component)
        self.assertFalse(component.with_user(unassigned_manager).can_manage_component)

    def test_system_administrator_still_needs_native_project_access(self):
        system_user = new_test_user(
            self.env,
            login="component_system_without_project_access",
            groups="base.group_system,project.group_project_user",
        )
        private_project = self.env["project.project"].create({
            "name": "Private component configuration",
            "privacy_visibility": "employees",
            "agile_enabled": True,
            "agile_key": "PRIVCOMP",
        })
        component = self.component_model.create({
            "name": "Private component", "project_id": private_project.id,
        })
        private_project.write({"privacy_visibility": "followers"})

        self.assertFalse(private_project.with_user(system_user).has_access("read"))
        self.assertFalse(component.with_user(system_user).has_access("read"))
        with self.assertRaises(AccessError):
            self.component_model.with_user(system_user).create({
                "name": "Unauthorized component",
                "project_id": private_project.id,
            })

    def test_fix_version_is_same_project_and_archives_are_historical(self):
        version = self.env["project.version"].create({
            "name": "2.0",
            "project_id": self.project.id,
        })
        issue = self.env["project.task"].create({
            "name": "Versioned issue",
            "project_id": self.project.id,
            "version_id": version.id,
        })
        foreign_version = self.env["project.version"].create({
            "name": "Foreign 2.0",
            "project_id": self.other_project.id,
        })
        with self.assertRaisesRegex(ValidationError, "same project"):
            issue.write({"version_id": foreign_version.id})
        with self.assertRaisesRegex(UserError, "cannot be moved"):
            version.write({"project_id": self.other_project.id})
        self.assertEqual(version.project_id, self.project)
        version.active = False
        issue.write({"name": "Existing assignment retained"})
        self.assertEqual(issue.version_id, version)
        new_issue = self.env["project.task"].create({
            "name": "New issue", "project_id": self.project.id,
        })
        with self.assertRaisesRegex(ValidationError, "Archived fix versions"):
            new_issue.write({"version_id": version.id})


class TestAgileComponentDefaultAssignee(TransactionCase):
    """S-1122: a component can name the assignee an issue gets when it has none."""

    def setUp(self):
        super().setUp()
        self.owner = new_test_user(self.env, login="comp_owner", groups="project.group_project_user")
        self.other = new_test_user(self.env, login="comp_other", groups="project.group_project_user")
        self.project = self.env["project.project"].create({
            "name": "Default assignee", "agile_enabled": True, "agile_key": "DAS",
        })
        self.component = self.env["agile.project.component"].create({
            "name": "Checkout", "project_id": self.project.id, "owner_id": self.owner.id,
        })
        # Odoo puts the creator on a new task; these tests start from an unassigned one.
        self.Task = self.env["project.task"].with_context(default_user_ids=False)

    def test_a_new_issue_without_an_assignee_gets_the_default_assignee(self):
        issue = self.Task.create({
            "name": "A", "project_id": self.project.id, "agile_component_id": self.component.id
        })
        self.assertEqual(issue.user_ids, self.owner)

    def test_an_assignee_already_given_is_kept(self):
        issue = self.Task.create({
            "name": "B", "project_id": self.project.id, "agile_component_id": self.component.id,
            "user_ids": [(6, 0, self.other.ids)],
        })
        self.assertEqual(issue.user_ids, self.other)

    def test_choosing_the_component_later_assigns_only_an_unassigned_issue(self):
        free = self.Task.create({"name": "C", "project_id": self.project.id})
        taken = self.Task.create({"name": "D", "project_id": self.project.id, "user_ids": [(6, 0, self.other.ids)]})
        (free | taken).write({"agile_component_id": self.component.id})
        self.assertEqual(free.user_ids, self.owner)
        self.assertEqual(taken.user_ids, self.other)

    def test_a_component_without_a_default_assignee_assigns_no_one(self):
        plain = self.env["agile.project.component"].create({"name": "Plain", "project_id": self.project.id})
        issue = self.Task.create({
            "name": "E", "project_id": self.project.id, "agile_component_id": plain.id,
        })
        self.assertFalse(issue.user_ids)
