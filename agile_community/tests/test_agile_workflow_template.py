import base64
import json

from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, new_test_user
from .pro_guard import needs_pro


class TestWorkflowTemplate(TransactionCase):
    """T-1141: copy a workflow to another project or move it as a file."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, login="wt_manager", groups="project.group_project_manager")
        cls.dev = new_test_user(cls.env, login="wt_dev", groups="project.group_project_user")
        Project = cls.env["project.project"].with_user(cls.manager)
        cls.source = Project.create({"name": "Template source", "agile_enabled": True, "agile_key": "WTS", "agile_method": "kanban"})
        cls.target = Project.create({"name": "Template target", "agile_enabled": True, "agile_key": "WTT", "agile_method": "kanban"})
        Member = cls.env["agile.project.member"].sudo()
        for user, role in ((cls.dev, "contributor"),):
            Member.search([("project_id", "=", cls.source.id), ("user_id", "=", user.id)]).unlink()
            Member.create({"project_id": cls.source.id, "user_id": user.id, "role": role})
        cls.Workflow = cls.env["agile.workflow"].with_user(cls.manager)
        cls.default = cls.Workflow.search([("project_id", "=", cls.source.id), ("is_default", "=", True)])

    def _shape(self, workflow):
        return (len(workflow.status_ids), len(workflow.transition_ids))

    def test_the_template_is_plain_data_that_names_things_by_words(self):
        data = self.default.with_user(self.manager).agile_template_data()
        self.assertEqual(json.loads(json.dumps(data)), data)
        self.assertEqual(data["format"], "agile_workflow")
        self.assertEqual([s["name"] for s in data["statuses"]], [s.stage_id.name for s in self.default.status_ids.sorted("sequence")])
        self.assertEqual(len(data["moves"]), len(self.default.transition_ids))
        self.assertIsInstance(data["moves"][0]["from"], str)

    def test_a_copy_is_a_new_workflow_and_leaves_the_target_default_alone(self):
        target_default = self.Workflow.search([("project_id", "=", self.target.id), ("is_default", "=", True)])
        before = self._shape(target_default)
        copy, notes = self.default.agile_copy_to_project(self.target)
        self.assertEqual(copy.project_id, self.target)
        self.assertFalse(copy.is_default)
        self.assertEqual(self._shape(copy), self._shape(self.default))
        self.assertEqual(self._shape(target_default), before)
        self.assertEqual(notes, [])
        original = {(t.from_status_id.stage_id.name, t.to_status_id.stage_id.name): (t.name, t.allow_contributor, t.allow_manager) for t in self.default.transition_ids}
        copied = {(t.from_status_id.stage_id.name, t.to_status_id.stage_id.name): (t.name, t.allow_contributor, t.allow_manager) for t in copy.transition_ids}
        self.assertEqual(copied, original)

    def test_a_missing_status_is_created_and_reported(self):
        workflow = self.Workflow.create({"name": "With review", "project_id": self.source.id})
        workflow.agile_add_status("Design review", "progress")
        copy, notes = workflow.agile_copy_to_project(self.target)
        self.assertIn("Design review", copy.status_ids.mapped("name"))
        self.assertTrue(any("Design review" in note for note in notes))
        self.assertTrue(self.env["project.task.type"].search([("name", "=", "Design review"), ("project_ids", "=", self.target.id)]))

    @needs_pro("agile.custom.field")
    def test_what_the_target_lacks_is_left_out_and_reported(self):
        field = self.env["agile.custom.field"].with_user(self.manager).create(
            {"name": "Customer", "project_id": self.source.id, "field_type": "text"}
        )
        Member = self.env["agile.project.member"].sudo()
        Member.search([("project_id", "=", self.target.id), ("user_id", "=", self.dev.id)]).unlink()
        Member.create({"project_id": self.target.id, "user_id": self.dev.id, "role": "stakeholder"})
        move = self.default.transition_ids[:1]
        move.sudo().write({"required_custom_field_ids": [(6, 0, field.ids)], "approver_ids": [(6, 0, self.dev.ids)]})
        copy, notes = self.default.agile_copy_to_project(self.target)
        self.assertEqual(len(copy.transition_ids), len(self.default.transition_ids))
        self.assertFalse(copy.transition_ids.required_custom_field_ids)
        self.assertFalse(copy.transition_ids.approver_ids.mapped("login"))
        self.assertTrue(any("Customer" in note for note in notes))
        self.assertTrue(any(self.dev.login in note for note in notes))

    def test_only_a_manager_of_both_projects_shares(self):
        with self.assertRaises(AccessError):
            self.default.with_user(self.dev).agile_template_data()
        other = self.env["project.project"].sudo().create(
            {"name": "Not mine", "agile_enabled": True, "agile_key": "WTN", "agile_method": "kanban"}
        )
        with self.assertRaises(AccessError):
            self.default.with_user(self.manager).agile_copy_to_project(other)

    def test_a_file_that_is_not_a_workflow_is_refused(self):
        Workflow = self.Workflow
        for data in (None, [], {"format": "other"}, {"format": "agile_workflow", "version": 99},
                     {"format": "agile_workflow", "version": 1, "statuses": [], "moves": []},
                     {"format": "agile_workflow", "version": 1, "moves": [],
                      "statuses": [{"name": "X", "category": "nonsense"}]}):
            with self.assertRaises(UserError, msg=str(data)):
                Workflow.agile_create_from_template(self.target, data)

    def test_the_wizard_imports_a_file_and_names_repeat_imports_apart(self):
        text = json.dumps(self.default.agile_template_data())
        Wizard = self.env["agile_community.workflow_template_wizard"].with_user(self.manager)
        names = []
        for _ in range(2):
            wizard = Wizard.create({
                "project_id": self.target.id, "file": base64.b64encode(text.encode()).decode(), "filename": "flow.json",
            })
            wizard.action_import()
            names.append(wizard.new_workflow_id.name)
            self.assertIn("Created the workflow", wizard.report)
        self.assertEqual(len(set(names)), 2)
        with self.assertRaises(UserError):
            Wizard.create({"project_id": self.target.id, "file": base64.b64encode(b"not json").decode()}).action_import()
