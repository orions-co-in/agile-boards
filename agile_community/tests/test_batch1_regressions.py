from odoo.tests import Form
from odoo.tests.common import TransactionCase, new_test_user


class TestAgileEnablingAndNativeTasks(TransactionCase):
    def setUp(self):
        super().setUp()
        self.manager = new_test_user(
            self.env, login="agile_setup_pm", groups="project.group_project_manager"
        )

    def test_project_manager_sees_setup_fields_while_enabling_agile(self):
        project = self.env["project.project"].with_user(self.manager).create(
            {"name": "Plain project"}
        )
        with Form(project.with_user(self.manager)) as form:
            self.assertFalse(form.can_manage_agile_team)
            form.agile_enabled = True
            # The key is only editable once the setup group is visible.
            self.assertTrue(form.can_manage_agile_team)
            form.agile_key = "SETUP"
        self.assertTrue(project.agile_enabled)
        self.assertEqual(project.agile_key, "SETUP")
        self.assertEqual(project._agile_role_for_user(self.manager), "manager")

    def test_native_task_in_non_agile_project_ignores_empty_relations(self):
        project = self.env["project.project"].create({"name": "Native project"})
        task = self.env["project.task"].create({
            "name": "Ordinary task",
            "project_id": project.id,
            "agile_related_issue_ids": [(6, 0, [])],
            "agile_duplicate_issue_ids": [(6, 0, [])],
        })
        self.assertFalse(task.agile_issue)


class TestQuickFilterLifecycle(TransactionCase):
    def setUp(self):
        super().setUp()
        self.project = self.env["project.project"].create({
            "name": "Filter project", "agile_enabled": True, "agile_key": "QFL",
        })

    def test_priority_filter_can_be_edited_and_archived(self):
        quick_filter = self.env["agile.project.quick.filter"].create({
            "name": "Urgent", "project_id": self.project.id,
            "filter_type": "priority", "priority": "1",
        })
        quick_filter.write({"name": "Urgent work"})
        quick_filter.write({"active": False})
        self.assertFalse(quick_filter.active)
        self.assertEqual(quick_filter.name, "Urgent work")


class TestEpicCreationAndBulkPreview(TransactionCase):
    def setUp(self):
        super().setUp()
        self.project = self.env["project.project"].create({
            "name": "Epic project", "agile_enabled": True, "agile_key": "EPC",
        })

    def test_epic_list_allows_creating_an_epic(self):
        action = self.project.action_view_agile_roadmap_epics()
        self.assertNotIn("create", action["context"])
        epic_type = self.env.ref("agile_community.agile_task_type_epic")
        self.assertEqual(action["context"]["default_agile_task_type_id"], epic_type.id)
        epic = self.env["project.task"].with_context(**action["context"]).create(
            {"name": "New epic"}
        )
        self.assertTrue(epic.agile_is_epic)

    def test_bulk_preview_refreshes_before_apply(self):
        issue = self.env["project.task"].create({
            "name": "Unassigned", "project_id": self.project.id,
        })
        wizard_model = self.env["agile_community.bulk_update_wizard"].with_context(
            default_task_ids=issue.ids
        )
        with Form(wizard_model) as form:
            self.assertIn("Select changes", form.preview_result)
            form.update_assignees = True
            form.assignee_operation = "replace"
            form.assignee_ids.add(self.env.ref("base.user_admin"))
            self.assertIn("Set assignees to", form.preview_result)
            self.assertIn("Can be updated", form.preview_result)


class TestBatch2Regressions(TransactionCase):
    def setUp(self):
        super().setUp()
        self.project = self.env["project.project"].create({
            "name": "Batch two", "agile_enabled": True, "agile_key": "BTW",
        })

    def test_work_method_change_with_linked_release_does_not_fail(self):
        release = self.env["project.version"].create({
            "name": "R1", "project_id": self.project.id,
        })
        self.env["project.task"].create({
            "name": "In release", "project_id": self.project.id,
            "version_id": release.id,
        })
        with Form(self.project) as form:
            form.agile_method = "kanban"
        self.assertEqual(self.project.agile_method, "kanban")
        self.assertEqual(release.issue_count, 1)

    def test_quick_filter_priority_labels_match_native(self):
        selection = dict(
            self.env["agile.project.quick.filter"]._fields["priority"].selection
        )
        native = dict(self.env["project.task"]._fields["priority"].selection)
        self.assertEqual(selection, native)

    def test_empty_epic_list_explains_how_to_create(self):
        action = self.project.action_view_agile_roadmap_epics()
        self.assertIn("create an Epic", action["help"])


class TestBatch3Regressions(TransactionCase):
    def test_new_component_form_computes_issue_count(self):
        project = self.env["project.project"].create({
            "name": "Component form", "agile_enabled": True, "agile_key": "CMF",
        })
        form = Form(
            self.env["agile.project.component"].with_context(default_project_id=project.id)
        )
        form.name = "New area"
        self.assertEqual(form.issue_count, 0)

    def test_new_sprint_form_is_editable_before_project_is_chosen(self):
        project = self.env["project.project"].create({
            "name": "Sprint form", "agile_enabled": True, "agile_key": "SPF",
        })
        with Form(self.env["project.sprint"]) as form:
            self.assertTrue(form.can_manage_project_sprint)
            form.name = "Sprint 1"
            form.project_id = project
        self.assertEqual(
            self.env["project.sprint"].search([("name", "=", "Sprint 1")]).project_id,
            project,
        )

    def test_sprint_list_view_is_not_the_read_only_velocity_list(self):
        views = self.env["project.sprint"].get_views([(False, "list")])
        self.assertNotIn('create="0"', views["views"]["list"]["arch"])


class TestTemplateAndImport(TransactionCase):
    def setUp(self):
        super().setUp()
        self.project = self.env["project.project"].create({
            "name": "Tpl import", "agile_enabled": True, "agile_key": "TPI",
        })
        self.release = self.env["project.version"].create({
            "name": "Rel", "project_id": self.project.id,
        })
        self.issue = self.env["project.task"].create({
            "name": "Source", "project_id": self.project.id,
            "version_id": self.release.id,
        })

    def test_convert_to_template_drops_release(self):
        action = self.issue.action_convert_to_template()
        template = self.env["project.task"].browse(action["res_id"])
        self.assertTrue(template.is_template)
        self.assertFalse(template.version_id)
        self.assertEqual(self.issue.version_id, self.release)

    def test_import_by_issue_key_with_project_column(self):
        result = self.env["project.task"].load(
            ["issue_key", "name", "project_id"],
            [[self.issue.issue_key, "Renamed", self.project.name]],
        )
        self.assertFalse(result["messages"], result["messages"])
        self.assertEqual(self.issue.name, "Renamed")
