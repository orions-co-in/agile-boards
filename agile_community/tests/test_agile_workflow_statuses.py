import json

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user

from odoo.addons.agile_community.models.agile_workflow_editor import MAX_WORKFLOW_STATUSES


class StatusCase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, login="st_manager", groups="project.group_project_manager")
        cls.contributor = new_test_user(cls.env, login="st_contrib", groups="project.group_project_user")
        cls.project = cls.env["project.project"].with_user(cls.manager).create({
            "name": "Status project", "privacy_visibility": "employees",
            "agile_enabled": True, "agile_key": "STS",
        })
        member = cls.env["agile.project.member"].search([
            ("project_id", "=", cls.project.id), ("user_id", "=", cls.contributor.id)])
        member.sudo().role = "contributor"
        cls.workflow = cls.project.agile_workflow_ids

    def _add(self, name="In QA", category="review", user=None):
        return self.workflow.with_user(user or self.manager).agile_add_status(name, category)


class TestAgileWorkflowStatuses(StatusCase):
    """B-911: a manager adds and renames statuses; categories keep one main status."""

    def test_added_status_lands_after_its_category_and_the_main_one_stays(self):
        result = self._add()
        stage = self.env["project.task.type"].browse(result["stage_id"])
        self.assertEqual(stage.agile_status, "review")
        self.assertFalse(stage.agile_is_main)
        main = self.env["project.task.type"]._agile_main_stage(self.project, "review")
        self.assertTrue(main.agile_is_main)
        self.assertNotEqual(main, stage)
        ordered = self.workflow.status_ids.sorted(lambda s: (s.sequence, s.id)).mapped("name")
        self.assertEqual(ordered, ["Backlog", "To Do", "In Progress", "Review", "In QA", "Done", "Canceled"])
        stages = self.env["project.task.type"].search([
            ("project_ids", "=", self.project.id), ("agile_status", "!=", False)], order="sequence, id")
        self.assertEqual(stages.mapped("name"), ordered)

    def test_every_default_stage_is_the_main_one(self):
        stages = self.env["project.task.type"].search([
            ("project_ids", "=", self.project.id), ("agile_status", "!=", False)])
        self.assertEqual(len(stages), 6)
        self.assertTrue(all(stages.mapped("agile_is_main")))

    def test_actions_still_send_issues_to_the_main_status(self):
        self._add("Design review", "progress")
        issue = self.env["project.task"].with_user(self.manager).create({
            "name": "Plain issue", "project_id": self.project.id, "description": "x", "story_points": 1,
        })
        issue.action_agile_mark_ready()
        issue.action_agile_start()
        self.assertEqual(issue.stage_id.name, "In Progress")

    def test_only_managers_add_statuses(self):
        with self.assertRaises(AccessError):
            self._add(user=self.contributor)

    def test_names_must_be_filled_and_unique(self):
        with self.assertRaises(ValidationError):
            self._add(name="  ")
        self._add("In QA")
        with self.assertRaises(ValidationError):
            self._add("in qa", "progress")
        with self.assertRaises(ValidationError):
            self._add("Done", "done")

    def test_category_must_be_one_of_the_six(self):
        with self.assertRaises(ValidationError):
            self._add("Odd", "nowhere")

    def test_a_workflow_holds_at_most_twelve_statuses(self):
        for index in range(MAX_WORKFLOW_STATUSES - 6):
            self._add(f"Extra {index}", "progress")
        self.assertEqual(len(self.workflow.status_ids), MAX_WORKFLOW_STATUSES)
        with self.assertRaises(ValidationError):
            self._add("One too many", "progress")

    def test_renaming_a_status_renames_its_stage_and_keeps_names_unique(self):
        status = self.workflow.status_ids.filtered(lambda s: s.category == "review")
        status.with_user(self.manager).write({"name": "Peer review"})
        self.assertEqual(status.stage_id.name, "Peer review")
        with self.assertRaises(ValidationError):
            status.with_user(self.manager).write({"name": "Done"})
        with self.assertRaises(AccessError):
            status.with_user(self.contributor).write({"name": "Hacked"})

    def test_a_category_has_one_main_status(self):
        stage = self.env["project.task.type"].browse(self._add()["stage_id"])
        with self.assertRaises(ValidationError):
            stage.sudo().agile_is_main = True


class TestAgileWorkflowHideAndRemove(StatusCase):
    """B-912: hide, show, remove from a workflow, use an existing status, delete."""

    def _issue_in(self, stage, name="Held"):
        issue = self.env["project.task"].with_user(self.manager).create({
            "name": name, "project_id": self.project.id, "description": "x", "story_points": 1,
        })
        issue.sudo().write({"stage_id": stage.id})
        return issue

    def _extra(self, category="review", name="In QA"):
        return self.env["project.task.type"].browse(self._add(name, category)["stage_id"])

    def test_hiding_moves_issues_and_archives_the_stage(self):
        extra = self._extra()
        main = self.env["project.task.type"]._agile_main_stage(self.project, "review")
        issue = self._issue_in(extra)
        wf = self.workflow.with_user(self.manager)
        with self.assertRaises(ValidationError):
            wf.agile_hide_status(extra.id)  # issues are in it and no target was given
        wf.agile_hide_status(extra.id, main.id)
        self.assertFalse(extra.active)
        self.assertEqual(issue.stage_id, main)

    def test_the_only_status_of_a_category_cannot_be_hidden(self):
        done = self.env["project.task.type"]._agile_main_stage(self.project, "done")
        with self.assertRaises(ValidationError):
            self.workflow.with_user(self.manager).agile_hide_status(done.id)

    def test_hiding_the_main_hands_the_role_to_another_status_and_show_restores(self):
        extra = self._extra()
        main = self.env["project.task.type"]._agile_main_stage(self.project, "review")
        wf = self.workflow.with_user(self.manager)
        wf.agile_hide_status(main.id)
        self.assertTrue(extra.agile_is_main)
        self.assertFalse(main.agile_is_main)
        wf.agile_show_status(main.id)
        self.assertTrue(main.active)
        self.assertTrue(extra.agile_is_main)

    def test_hidden_status_is_refused_as_a_move_target(self):
        extra = self._extra("progress", "Design")
        self.workflow.with_user(self.manager).agile_hide_status(extra.id)
        issue = self._issue_in(self.env["project.task.type"]._agile_main_stage(self.project, "backlog"))
        with self.assertRaises(UserError):
            issue.sudo().write({"stage_id": extra.id})

    def test_remove_from_workflow_keeps_the_status_in_the_project(self):
        extra = self._extra()
        wf = self.workflow.with_user(self.manager)
        wf.agile_remove_status(extra.id)
        self.assertNotIn(extra, self.workflow.status_ids.stage_id)
        self.assertTrue(extra.active)
        wf.agile_use_status(extra.id)
        self.assertIn(extra, self.workflow.status_ids.stage_id)
        with self.assertRaises(ValidationError):
            wf.agile_use_status(extra.id)

    def test_remove_refuses_while_issues_are_in_it(self):
        extra = self._extra()
        self._issue_in(extra)
        with self.assertRaises(ValidationError):
            self.workflow.with_user(self.manager).agile_remove_status(extra.id)

    def test_delete_only_when_no_issue_ever_used_the_status(self):
        unused = self._extra(name="Never used")
        used = self._extra("progress", "Was used")
        issue = self._issue_in(used)
        wf = self.workflow.with_user(self.manager)
        wf.agile_delete_status(unused.id)
        self.assertFalse(unused.exists())
        self.env.cr.precommit.run()  # tracking is discarded for a record created in this transaction until then
        issue.sudo().write({"stage_id": self.env["project.task.type"]._agile_main_stage(self.project, "progress").id})
        self.env.cr.precommit.run()
        with self.assertRaises(ValidationError):
            wf.agile_delete_status(used.id)

    def test_contributors_cannot_hide_remove_or_delete(self):
        extra = self._extra()
        wf = self.workflow.with_user(self.contributor)
        for call in (wf.agile_hide_status, wf.agile_remove_status, wf.agile_delete_status, wf.agile_show_status):
            with self.assertRaises(AccessError):
                call(extra.id)

    def test_diagram_lists_hidden_and_available_statuses(self):
        extra = self._extra()
        wf = self.workflow.with_user(self.manager)
        wf.agile_remove_status(extra.id)
        diagram = self.workflow.with_user(self.manager).diagram
        self.assertEqual([a["name"] for a in diagram["available"]], ["In QA"])
        wf.agile_use_status(extra.id)
        wf.agile_hide_status(extra.id)
        self.workflow.invalidate_recordset()
        hidden = [s for s in self.workflow.with_user(self.manager).diagram["statuses"] if s["hidden"]]
        self.assertEqual([s["name"] for s in hidden], ["In QA"])


class TestAgileMoveConditions(StatusCase):
    """B-913: a move can require that sub-issues are closed and that the issue is not blocked."""

    def _move(self, source, target):
        return self.workflow.transition_ids.filtered(
            lambda t: t.from_status_id.category == source and t.to_status_id.category == target)

    def _issue(self, name="Parent", **vals):
        return self.env["project.task"].with_user(self.manager).create({
            "name": name, "project_id": self.project.id, "description": "Done thing", "story_points": 2,
            "user_ids": [(6, 0, self.manager.ids)], **vals,
        })

    def _to_review(self, issue):
        issue.action_agile_mark_ready()
        issue.action_agile_start()
        issue.action_agile_send_review()

    def test_conditions_are_off_by_default(self):
        self.assertFalse(any(self.workflow.transition_ids.mapped("require_no_open_subtasks")))
        self.assertFalse(any(self.workflow.transition_ids.mapped("require_not_blocked")))

    def test_open_sub_issues_stop_the_move_and_the_reason_says_how_many(self):
        self._move("review", "done").require_no_open_subtasks = True
        parent = self._issue()
        self._issue("Child 1", parent_id=parent.id)
        self._issue("Child 2", parent_id=parent.id)
        self._to_review(parent)
        self.assertIn("Before Done: finish its 2 open sub-issues.", parent.agile_transition_hint)
        self.assertEqual(parent.agile_step_reasons["done"], "Before Done: finish its 2 open sub-issues.")
        with self.assertRaises(UserError) as caught:
            parent.action_agile_complete()
        self.assertIn("finish its 2 open sub-issues", str(caught.exception))

    def test_the_move_works_once_sub_issues_are_closed(self):
        self._move("review", "done").require_no_open_subtasks = True
        parent = self._issue()
        child = self._issue("Child", parent_id=parent.id)
        self._to_review(parent)
        for step in ("mark_ready", "start", "send_review", "complete"):
            getattr(child, f"action_agile_{step}")()
        parent.action_agile_complete()
        self.assertEqual(parent.agile_status, "done")

    def test_blocked_issue_cannot_take_a_not_blocked_move(self):
        self._move("review", "done").require_not_blocked = True
        issue = self._issue()
        self._to_review(issue)
        issue.write({"agile_blocked": True, "agile_block_reason": "Waiting for the vendor"})
        with self.assertRaises(UserError) as caught:
            issue.action_agile_complete()
        self.assertIn("clear the blocker", str(caught.exception))
        issue.write({"agile_blocked": False})
        issue.action_agile_complete()
        self.assertEqual(issue.agile_status, "done")

    def test_a_drag_to_the_column_is_checked_too(self):
        self._move("review", "done").require_no_open_subtasks = True
        parent = self._issue()
        self._issue("Child", parent_id=parent.id)
        self._to_review(parent)
        done = self.env["project.task.type"]._agile_main_stage(self.project, "done")
        with self.assertRaises(UserError):
            parent.write({"stage_id": done.id})

    def test_allowed_moves_carry_the_reason_for_the_phone_sheet(self):
        self._move("review", "done").require_not_blocked = True
        issue = self._issue()
        self._to_review(issue)
        issue.write({"agile_blocked": True, "agile_block_reason": "x"})
        moves = {m["stage"]: m["reason"] for m in issue.agile_allowed_moves()}
        self.assertEqual(moves["Done"], "clear the blocker")
        self.assertEqual(moves["In Progress"], "")

    def test_conditions_are_copied_with_a_workflow_and_logged(self):
        move = self._move("review", "done")
        move.with_user(self.manager).require_not_blocked = True
        copy = self.env["agile.workflow"].with_user(self.manager).create({
            "name": "Copy", "project_id": self.project.id})
        copied = copy.transition_ids.filtered(
            lambda t: t.from_status_id.category == "review" and t.to_status_id.category == "done")
        self.assertTrue(copied.require_not_blocked)

    def test_only_managers_change_conditions(self):
        move = self._move("review", "done")
        with self.assertRaises(AccessError):
            move.with_user(self.contributor).require_not_blocked = True


class TestAgileCustomMoves(StatusCase):
    """NU-08: a move the standard buttons do not cover gets a button of its own."""

    def _setup_qa(self, contributor=True):
        result = self._add("In QA", "review")
        review = self.workflow.status_ids.filtered(lambda s: s.name == "Review")
        qa = self.workflow.status_ids.filtered(lambda s: s.name == "In QA")
        move = self.env["agile.workflow.transition"].create({
            "workflow_id": self.workflow.id, "name": "Send to QA",
            "from_status_id": review.id, "to_status_id": qa.id,
            "allow_contributor": contributor, "allow_reviewer": True, "allow_manager": True,
        })
        issue = self.env["project.task"].with_user(self.manager).create({
            "name": "QA issue", "project_id": self.project.id, "description": "x", "story_points": 1,
            "user_ids": [(6, 0, [self.contributor.id])],
        })
        issue.action_agile_mark_ready()
        issue.action_agile_start()
        issue.action_agile_send_review()
        return issue, move

    def test_custom_move_is_offered_and_taken(self):
        issue, move = self._setup_qa()
        moves = json.loads(issue.with_user(self.contributor).agile_custom_moves)
        self.assertEqual([m["name"] for m in moves], ["Send to QA"])
        issue.with_user(self.contributor).action_agile_custom_move(move.id)
        self.assertEqual(issue.stage_id.name, "In QA")

    def test_no_custom_move_for_a_role_the_move_does_not_allow(self):
        issue, move = self._setup_qa(contributor=False)
        self.assertFalse(issue.with_user(self.contributor).agile_custom_moves)
        with self.assertRaises(UserError):
            issue.with_user(self.contributor).action_agile_custom_move(move.id)

    def test_standard_moves_are_not_listed_as_custom(self):
        issue, move = self._setup_qa()
        names = [m["name"] for m in json.loads(issue.with_user(self.manager).agile_custom_moves)]
        self.assertEqual(names, ["Send to QA"])
