from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user
from odoo.tools import mute_logger

from odoo.addons.agile_community.models.agile_workflow import DEFAULT_STATUS_ORDER
from .pro_guard import needs_pro


class TestAgileWorkflow(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, login="wf_manager", groups="project.group_project_manager")
        cls.contributor = new_test_user(cls.env, login="wf_contributor", groups="project.group_project_user")
        cls.reviewer = new_test_user(cls.env, login="wf_reviewer", groups="project.group_project_user")
        cls.outsider = new_test_user(cls.env, login="wf_outsider", groups="project.group_project_user")
        cls.project = cls.env["project.project"].with_user(cls.manager).create({
            "name": "Workflow project",
            "privacy_visibility": "employees",
            "agile_enabled": True,
            "agile_key": "WFL",
        })
        for user, role in ((cls.contributor, "contributor"), (cls.reviewer, "reviewer")):
            member = cls.env["agile.project.member"].search([
                ("project_id", "=", cls.project.id), ("user_id", "=", user.id),
            ])
            if member:
                member.with_user(cls.manager).role = role
            else:
                cls.env["agile.project.member"].with_user(cls.manager).create({
                    "project_id": cls.project.id, "user_id": user.id, "role": role,
                })
        # Every internal user starts as a member; the outsider is the one who is not.
        cls.env["agile.project.member"].sudo().search([
            ("project_id", "=", cls.project.id), ("user_id", "=", cls.outsider.id),
        ]).unlink()
        cls.stages = {
            stage.agile_status: stage for stage in cls.project.type_ids.filtered("agile_status")
        }
        cls.workflow = cls.project.agile_workflow_ids

    def _status(self, category, workflow=None):
        return (workflow or self.workflow).status_ids.filtered(lambda s: s.category == category)

    def test_project_gets_one_default_workflow_with_the_six_statuses(self):
        self.assertEqual(len(self.workflow), 1)
        self.assertTrue(self.workflow.is_default)
        self.assertEqual(self.workflow.status_ids.sorted("sequence").mapped("category"), DEFAULT_STATUS_ORDER)
        self.assertEqual(len(self.workflow.transition_ids), 12)
        # Seeding again changes nothing.
        self.project._ensure_agile_default_workflow()
        self.assertEqual(self.project.agile_workflow_ids, self.workflow)

    def test_default_workflow_allows_exactly_what_the_hard_coded_rules_allow(self):
        issue = self.env["project.task"].with_user(self.manager).create({
            "name": "Parity", "project_id": self.project.id,
        })
        for user, role in ((self.contributor, "contributor"), (self.reviewer, "reviewer"), (self.manager, "manager")):
            for source in DEFAULT_STATUS_ORDER:
                issue.sudo().stage_id = self.stages[source]
                as_user = issue.with_user(user)
                from_workflow = {t.to_status_id.category for t in as_user._agile_allowed_transitions()}
                from_rules = set()
                for target in DEFAULT_STATUS_ORDER:
                    try:
                        as_user._check_agile_transition(target)
                    except UserError:
                        continue
                    if target != source:
                        from_rules.add(target)
                self.assertEqual(from_workflow, from_rules, f"{role}: {source}")

    def test_role_without_membership_gets_no_transitions(self):
        issue = self.env["project.task"].with_user(self.manager).create({
            "name": "Closed door", "project_id": self.project.id,
        })
        self.assertFalse(issue.with_user(self.outsider)._agile_allowed_transitions())

    def test_issue_type_with_its_own_workflow_uses_it_and_others_use_the_default(self):
        bug = self.env["agile_community.task_type"].search([("is_epic", "=", False)], limit=1)
        other = self.env["agile_community.task_type"].search([("is_epic", "=", False), ("id", "!=", bug.id)], limit=1)
        custom = self.env["agile.workflow"].with_user(self.manager).create({
            "name": "Bugs", "project_id": self.project.id, "task_type_ids": [(6, 0, bug.ids)],
        })
        issue = self.env["project.task"].with_user(self.manager).create({
            "name": "Typed", "project_id": self.project.id, "agile_task_type_id": bug.id,
        })
        self.assertEqual(issue._agile_workflow(), custom)
        issue.sudo().agile_task_type_id = other
        self.assertEqual(issue._agile_workflow(), self.workflow)

    def test_one_default_and_one_workflow_per_issue_type(self):
        workflows = self.env["agile.workflow"].with_user(self.manager)
        with self.assertRaises(ValidationError):
            workflows.create({"name": "Second default", "project_id": self.project.id, "is_default": True})
        bug = self.env["agile_community.task_type"].search([("is_epic", "=", False)], limit=1)
        workflows.create({"name": "A", "project_id": self.project.id, "task_type_ids": [(6, 0, bug.ids)]})
        with self.assertRaises(ValidationError):
            workflows.create({"name": "B", "project_id": self.project.id, "task_type_ids": [(6, 0, bug.ids)]})

    def test_transition_rules(self):
        transitions = self.env["agile.workflow.transition"].with_user(self.manager)
        ready, progress = self._status("ready"), self._status("progress")
        with self.assertRaises(ValidationError):
            transitions.create({
                "name": "Loop", "workflow_id": self.workflow.id,
                "from_status_id": ready.id, "to_status_id": ready.id,
            })
        with self.assertRaises(Exception), mute_logger("odoo.sql_db"), self.cr.savepoint():  # the pair has Start
            transitions.create({
                "name": "Again", "workflow_id": self.workflow.id,
                "from_status_id": ready.id, "to_status_id": progress.id,
            })
        other_project = self.env["project.project"].with_user(self.manager).create({
            "name": "Other", "privacy_visibility": "employees", "agile_enabled": True, "agile_key": "OTH",
        })
        foreign = other_project.agile_workflow_ids.status_ids[:1]
        with self.assertRaises(ValidationError):
            transitions.create({
                "name": "Cross", "workflow_id": self.workflow.id,
                "from_status_id": ready.id, "to_status_id": foreign.id,
            })

    def test_status_must_use_a_stage_of_the_project(self):
        other = self.env["project.project"].with_user(self.manager).create({
            "name": "Elsewhere", "privacy_visibility": "employees", "agile_enabled": True, "agile_key": "ELS",
        })
        foreign_stage = other.type_ids.filtered("agile_status")[:1]
        with self.assertRaises(ValidationError):
            self.env["agile.workflow.status"].with_user(self.manager).create({
                "workflow_id": self.workflow.id, "stage_id": foreign_stage.id,
            })

    def test_only_the_projects_manager_changes_workflows_and_the_default_stays(self):
        with self.assertRaises(AccessError):
            self.workflow.with_user(self.contributor).write({"name": "Mine"})
        with self.assertRaises(AccessError):
            self.workflow.transition_ids[:1].with_user(self.contributor).write({"allow_contributor": True})
        with self.assertRaises(AccessError):
            self.env["agile.workflow"].with_user(self.outsider).create({
                "name": "Sneaky", "project_id": self.project.id,
            })
        self.workflow.with_user(self.manager).write({"name": "Team flow"})
        self.assertEqual(self.workflow.name, "Team flow")
        with self.assertRaises(ValidationError):
            self.workflow.with_user(self.manager).unlink()
        self.assertTrue(self.workflow.with_user(self.contributor).transition_ids)  # members can read

    def test_outsider_cannot_read_the_workflow(self):
        self.assertFalse(self.env["agile.workflow"].with_user(self.outsider).search([("project_id", "=", self.project.id)]))

    def test_default_transitions_require_what_the_hard_coded_rules_require(self):
        issue = self.env["project.task"].with_user(self.manager).create({
            "name": "Needs", "project_id": self.project.id,
        })
        assignee = self.manager
        for has_assignee in (False, True):
            for has_description in (False, True):
                issue.sudo().write({
                    "user_ids": [(6, 0, assignee.ids if has_assignee else [])],
                    "description": "<p>Written.</p>" if has_description else False,
                })
                for transition in self.workflow.transition_ids:
                    target = transition.to_status_id.category
                    try:
                        issue._check_agile_transition_required_fields(target)
                        hard_coded_ok = True
                    except UserError:
                        hard_coded_ok = False
                    self.assertEqual(
                        not transition.missing_fields(issue), hard_coded_ok,
                        f"{transition.from_status_id.category} to {target} "
                        f"(assignee={has_assignee}, description={has_description})",
                    )

    def test_hint_names_what_the_next_moves_still_need_and_clears_when_filled(self):
        issue = self.env["project.task"].with_user(self.manager).create({
            "name": "Hinted", "project_id": self.project.id,
        })
        issue.sudo().write({"stage_id": self.stages["ready"].id, "user_ids": [(5, 0, 0)]})
        hint = issue.agile_transition_hint
        self.assertIn("Before In Progress: add an assignee.", hint)
        self.assertEqual(issue.agile_missing_fields, "user_ids")
        issue.sudo().user_ids = self.manager
        self.assertFalse(issue.agile_transition_hint)
        issue.sudo().stage_id = self.stages["progress"]
        issue.sudo().description = False
        self.assertIn("add a description", issue.agile_transition_hint)
        self.assertIn("description", issue.agile_missing_fields)

    def test_only_issue_fields_that_can_be_checked_are_allowed_as_requirements(self):
        fields_model = self.env["agile.workflow.field"]
        with self.assertRaises(ValueError):
            fields_model.create({"code": "name", "name": "Title", "phrase": "a title"})
        sprint = fields_model.search([("code", "=", "sprint_id")])
        self.workflow.transition_ids[:1].with_user(self.manager).required_field_ids = sprint
        issue = self.env["project.task"].with_user(self.manager).create({
            "name": "No sprint", "project_id": self.project.id,
        })
        self.assertEqual(self.workflow.transition_ids[:1].missing_fields(issue), ["sprint_id"])

    def test_allowed_moves_lists_what_the_current_role_may_do(self):
        issue = self.env["project.task"].with_user(self.manager).create({
            "name": "Phone", "project_id": self.project.id,
        })
        issue.sudo().stage_id = self.stages["backlog"]
        moves = issue.with_user(self.contributor).agile_allowed_moves()
        self.assertEqual(moves, [{
            "name": "Plan into sprint", "stage_id": self.stages["ready"].id, "stage": self.stages["ready"].name,
            "reason": "",
        }])
        self.assertEqual(
            sorted(m["name"] for m in issue.with_user(self.manager).agile_allowed_moves()),
            ["Cancel", "Plan into sprint"],
        )
        with self.assertRaises(AccessError):
            issue.with_user(self.outsider).agile_allowed_moves()


    # ---- the workflow decides (W-204) ----

    def _issue_in(self, status, name="Flow", **extra):
        issue = self.env["project.task"].with_user(self.manager).create({
            "name": name, "project_id": self.project.id, **extra,
        })
        issue.sudo().write({
            "stage_id": self.stages[status].id,
            "user_ids": [(6, 0, self.manager.ids)],
            "description": "<p>Written.</p>",
        })
        return issue

    def _transition(self, source, target, workflow=None):
        workflow = workflow or self.workflow
        return workflow.transition_ids.filtered(
            lambda t: t.from_status_id.category == source and t.to_status_id.category == target
        )

    def test_removing_a_role_from_a_transition_removes_the_move_and_the_button(self):
        issue = self._issue_in("ready")
        self.assertTrue(issue.with_user(self.contributor).can_agile_start)
        self._transition("ready", "progress").with_user(self.manager).allow_contributor = False
        contributor_issue = issue.with_user(self.contributor)
        self.assertFalse(contributor_issue.can_agile_start)
        with self.assertRaises(UserError):
            contributor_issue.action_agile_start()
        issue.with_user(self.manager).action_agile_start()  # managers keep it
        self.assertEqual(issue.agile_status, "progress")

    def test_a_workflow_for_an_issue_type_allows_its_own_moves(self):
        bug = self.env["agile_community.task_type"].search([("is_epic", "=", False)], limit=1)
        custom = self.env["agile.workflow"].with_user(self.manager).create({
            "name": "Bugs", "project_id": self.project.id, "task_type_ids": [(6, 0, bug.ids)],
        })
        statuses = {status.category: status for status in custom.status_ids}
        self.env["agile.workflow.transition"].with_user(self.manager).create({
            "name": "Straight to work", "workflow_id": custom.id,
            "from_status_id": statuses["backlog"].id, "to_status_id": statuses["progress"].id,
            "allow_contributor": True,
        })
        typed = self._issue_in("backlog", "Typed", agile_task_type_id=bug.id)
        plain = self._issue_in("backlog", "Plain")
        typed.with_user(self.contributor).write({"stage_id": self.stages["progress"].id})
        self.assertEqual(typed.agile_status, "progress")
        with self.assertRaises(UserError):
            plain.with_user(self.contributor).write({"stage_id": self.stages["progress"].id})
        # A move the typed workflow does not list is refused for that type.
        with self.assertRaises(UserError):
            typed.with_user(self.contributor).write({"stage_id": self.stages["done"].id})

    def test_required_fields_are_whatever_the_transition_lists(self):
        issue = self._issue_in("progress")
        issue.sudo().description = False
        review = self._transition("progress", "review")
        with self.assertRaises(UserError):
            issue.with_user(self.manager).action_agile_send_review()
        review.with_user(self.manager).required_field_ids = self.env["agile.workflow.field"].search(
            [("code", "=", "user_ids")]
        )
        issue.with_user(self.manager).action_agile_send_review()  # description no longer needed
        self.assertEqual(issue.agile_status, "review")
        ready = self._transition("backlog", "ready")
        ready.with_user(self.manager).required_field_ids = self.env["agile.workflow.field"].search(
            [("code", "=", "sprint_id")]
        )
        loose = self._issue_in("backlog", "Loose")
        with self.assertRaises(UserError) as caught:
            loose.with_user(self.manager).action_agile_mark_ready()
        self.assertIn("a sprint", str(caught.exception))
        self.assertEqual(loose.agile_status, "backlog")

    @needs_pro("agile.custom.field")
    def test_a_move_can_require_a_project_field(self):
        severity = self.env["agile.custom.field"].with_user(self.manager).create(
            {"name": "Severity", "project_id": self.project.id, "field_type": "text"})
        issue = self._issue_in("progress")
        review = self._transition("progress", "review")
        review.with_user(self.manager).required_custom_field_ids = severity
        with self.assertRaises(UserError) as caught:
            issue.with_user(self.manager).action_agile_send_review()
        self.assertIn("a value for Severity", str(caught.exception))
        self.assertIn("Severity", issue.agile_transition_hint)
        value = issue.agile_custom_value_ids.filtered(lambda v: v.field_id == severity)
        value.sudo().value_char = "High"
        issue.invalidate_recordset()
        issue.with_user(self.manager).action_agile_send_review()
        self.assertEqual(issue.agile_status, "review")

    @needs_pro("agile.custom.field")
    def test_a_project_field_rule_stops_a_drag_and_names_the_field(self):
        severity = self.env["agile.custom.field"].with_user(self.manager).create(
            {"name": "Severity", "project_id": self.project.id, "field_type": "text"})
        self._transition("progress", "review").with_user(self.manager).required_custom_field_ids = severity
        issue = self._issue_in("progress")
        with self.assertRaises(UserError) as caught:
            issue.with_user(self.contributor).write({"stage_id": self.stages["review"].id})
        self.assertIn("Severity", str(caught.exception))
        self.assertEqual(issue.agile_status, "progress")

    @needs_pro("agile.custom.field")
    def test_a_move_cannot_require_another_projects_field(self):
        other = self.env["project.project"].create({"name": "Other", "agile_enabled": True, "agile_key": "OTH"})
        foreign = self.env["agile.custom.field"].sudo().create(
            {"name": "Foreign", "project_id": other.id, "field_type": "text"})
        with self.assertRaises(ValidationError):
            self._transition("progress", "review").sudo().required_custom_field_ids = foreign

    @needs_pro("agile.custom.field")
    def test_the_canvas_offers_project_fields_and_the_note_names_them(self):
        severity = self.env["agile.custom.field"].with_user(self.manager).create(
            {"name": "Severity", "project_id": self.project.id, "field_type": "text"})
        self.assertEqual(self.workflow.diagram["custom_needs"], [{"id": severity.id, "name": "Severity"}])
        self.env.cr.precommit.run()
        before = self.project.message_ids
        self._transition("progress", "review").with_user(self.manager).required_custom_field_ids = severity
        self.env.cr.precommit.run()
        self.assertIn("Description, Severity.", (self.project.message_ids - before).body)

    def test_workflow_setup_and_migration_paths_are_not_blocked(self):
        issue = self._issue_in("ready")
        self.workflow.transition_ids.sudo().unlink()
        issue.sudo().stage_id = self.stages["done"]  # workflow-less writes by the system still work
        self.assertEqual(issue.agile_status, "done")

    # ---- the editor (W-203) ----

    def _bug_type(self):
        return self.env["agile_community.task_type"].search([("is_epic", "=", False)], limit=1)

    def _new_workflow(self):
        return self.env["agile.workflow"].with_user(self.manager).create({
            "name": "Bugs", "project_id": self.project.id, "task_type_ids": [(6, 0, self._bug_type().ids)],
        })

    def test_new_workflow_starts_as_a_copy_of_the_default(self):
        custom = self._new_workflow()
        self.assertEqual(custom.status_ids.sorted("sequence").mapped("category"), DEFAULT_STATUS_ORDER)
        self.assertEqual(len(custom.transition_ids), len(self.workflow.transition_ids))
        start = self._transition("ready", "progress", custom)
        self.assertEqual(start.required_field_ids.mapped("code"), ["user_ids"])
        self.assertTrue(start.allow_contributor)
        # The copy is independent of the default.
        start.with_user(self.manager).allow_contributor = False
        self.assertTrue(self._transition("ready", "progress").allow_contributor)

    def test_reset_restores_the_default_and_is_refused_on_the_default(self):
        custom = self._new_workflow()
        self._transition("ready", "progress", custom).with_user(self.manager).unlink()
        custom.status_ids.filtered(lambda s: s.category == "review").with_user(self.manager).unlink()
        custom.with_user(self.manager).action_reset_to_default()
        self.assertEqual(len(custom.status_ids), 6)
        self.assertEqual(len(custom.transition_ids), 12)
        with self.assertRaises(ValidationError):
            self.workflow.with_user(self.manager).action_reset_to_default()
        with self.assertRaises(AccessError):
            custom.with_user(self.contributor).action_reset_to_default()

    def test_a_status_with_issues_cannot_be_removed(self):
        self._issue_in("review", "In review")
        review = self._status("review")
        with self.assertRaises(ValidationError) as caught:
            review.with_user(self.manager).unlink()
        self.assertIn("Move them first", str(caught.exception))
        self.assertEqual(review.issue_count, 1)
        custom = self._new_workflow()  # no issue of the Bugs type is in Review, so it may go
        custom.status_ids.filtered(lambda s: s.category == "review").with_user(self.manager).unlink()
        self.assertNotIn("review", custom.status_ids.mapped("category"))

    def test_saving_posts_one_note_listing_what_changed(self):
        self.env.cr.precommit.run()  # setup notes are not this test's business
        before = self.project.message_ids
        start = self._transition("ready", "progress")
        start.with_user(self.manager).allow_contributor = False
        start.with_user(self.manager).required_field_ids = self.env["agile.workflow.field"].search(
            [("code", "in", ["user_ids", "story_points"])]
        )
        self.env["agile.workflow.transition"].with_user(self.manager).create({
            "name": "Straight to work", "workflow_id": self.workflow.id,
            "from_status_id": self._status("backlog").id, "to_status_id": self._status("progress").id,
        })
        self.env.cr.precommit.run()
        notes = self.project.message_ids - before
        self.assertEqual(len(notes), 1)
        body = notes.body
        self.assertIn("Default workflow", body)
        self.assertIn("Contributors can no longer take Start.", body)
        self.assertIn("Start now needs: Assignee, Estimate.", body)
        self.assertIn("Added move Straight to work: Backlog to In Progress.", body)

    def test_only_a_manager_opens_the_editor_action(self):
        action = self.project.with_user(self.manager).action_open_agile_workflows()
        self.assertEqual(action["res_model"], "agile.workflow")
        self.assertEqual(action["domain"], [("project_id", "=", self.project.id)])
        with self.assertRaises(AccessError):
            self.project.with_user(self.contributor).action_open_agile_workflows()

    def test_diagram_describes_the_statuses_and_moves(self):
        self._issue_in("review", "Counted")
        diagram = self.workflow.diagram
        self.assertEqual([s["category"] for s in diagram["statuses"]], DEFAULT_STATUS_ORDER)
        review = next(s for s in diagram["statuses"] if s["category"] == "review")
        self.assertEqual(review["count"], 1)
        self.assertEqual(len(diagram["moves"]), 12)
        cancel = next(m for m in diagram["moves"] if m["name"] == "Cancel")
        self.assertEqual(cancel["roles"], ["Managers"])
        start = next(m for m in diagram["moves"] if m["name"] == "Start")
        self.assertEqual(start["roles"], ["Contributors", "Managers"])

    # ---- D-806: the canvas reads the diagram JSON for its rights and its needs catalog ----

    def test_diagram_says_who_may_edit_and_lists_what_a_move_can_need(self):
        diagram = self.workflow.with_user(self.manager).diagram
        self.assertTrue(diagram["editable"])
        self.assertEqual(
            {need["name"] for need in diagram["needs"]},
            set(self.env["agile.workflow.field"].search([]).mapped("name")),
        )
