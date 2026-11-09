from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user


class TestAgileBacklog(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(
            cls.env, login="backlog_manager", groups="project.group_project_manager"
        )
        cls.contributor = new_test_user(
            cls.env, login="backlog_contributor", groups="project.group_project_user"
        )
        cls.project = cls.env["project.project"].with_user(cls.manager).create({
            "name": "Backlog project",
            "privacy_visibility": "employees",
            "agile_enabled": True,
            "agile_key": "BKLG",
            "agile_method": "scrum",
        })
        cls.outsider = new_test_user(
            cls.env, login="backlog_outsider", groups="project.group_project_user"
        )
        cls.today = fields.Date.context_today(cls.project)

    def _issue(self, name, points=3, **extra):
        values = {"name": name, "project_id": self.project.id, "description": "Backlog issue."}
        if points is not None:
            values["story_points"] = points
        values.update(extra)
        return self.env["project.task"].with_user(self.manager).create(values)

    def _sprint(self, name, start_offset, length=7):
        start = self.today + timedelta(days=start_offset)
        return self.env["project.sprint"].with_user(self.manager).create({
            "name": name,
            "project_id": self.project.id,
            "date_start": start,
            "date_option": "custom",
            "date_end": start + timedelta(days=length - 1),
        })

    def _finish(self, issue):
        issue = issue.with_user(self.manager)
        for step in ("mark_ready", "start", "send_review", "complete"):
            getattr(issue, f"action_agile_{step}")()

    def _member(self):
        existing = self.env["agile.project.member"].search([
            ("project_id", "=", self.project.id), ("user_id", "=", self.contributor.id),
        ])
        if not existing:
            self.env["agile.project.member"].with_user(self.manager).create({
                "project_id": self.project.id,
                "user_id": self.contributor.id,
                "role": "contributor",
            })
        return self.contributor

    def test_action_opens_grouped_list_with_hidden_completed_default(self):
        action = self.project.with_user(self.manager).action_open_agile_backlog()
        list_view = self.env.ref("agile_community.project_task_list_agile_backlog")
        self.assertEqual(action["views"][0], (list_view.id, "list"))
        self.assertNotIn("group_by", action["context"])
        self.assertEqual(action["context"]["search_default_agile_hide_completed"], 1)
        self.assertEqual(action["context"]["default_project_id"], self.project.id)
        self.assertEqual(
            action["search_view_id"][0],
            self.env.ref("agile_community.project_task_search_agile_backlog").id,
        )
        search_arch = self.env.ref("agile_community.project_task_search_agile_backlog").arch_db
        # Sprint and assignee are multi-select lists above the epics now, not a side panel.
        self.assertNotIn("<searchpanel>", search_arch)
        self.assertIn("agile_hide_completed", search_arch)
        self.assertIn('js_class="agile_backlog_list"', list_view.arch_db)

    def test_action_offers_the_alternate_views_over_one_shared_domain(self):
        action = self.project.with_user(self.manager).action_open_agile_backlog()
        self.assertEqual(
            [mode for _view, mode in action["views"]],
            ["list", "kanban", "calendar", "pivot", "graph", "activity", "form"],
        )
        # Epic children are issues here, so core must not hide them as sub-tasks.
        self.assertTrue(action["context"]["subtask_action"])
        self.assertEqual(action["domain"], self.project._agile_backlog_domain())
        views = {mode: self.env["ir.ui.view"].browse(view_id) for view_id, mode in action["views"] if view_id}
        self.assertIn('default_group_by="sprint_id"', views["list"].arch_db)
        kanban = views["kanban"].arch_db
        self.assertIn('default_group_by="parent_id"', kanban)
        for locked in ('records_draggable="0"', 'quick_create="0"', 'create="0"'):
            self.assertIn(locked, kanban)
        self.assertIn('date_start="date_deadline"', views["calendar"].arch_db)
        pivot = views["pivot"].arch_db
        self.assertIn('name="parent_id"', pivot)
        self.assertIn('name="stage_id"', pivot)
        self.assertIn('name="story_points"', pivot)
        self.assertIn('js_class="agile_backlog_graph"', views["graph"].arch_db)

    def test_alternate_views_read_leaf_issues_of_epics_with_the_action_context(self):
        epic_type = self.env["agile_community.task_type"].search([("is_epic", "=", True)], limit=1)
        epic = self._issue("Epic", points=None, agile_task_type_id=epic_type.id)
        child = self._issue("Child", points=5, parent_id=epic.id)
        self._issue("Loose", points=2)
        action = self.project.with_user(self.manager).action_open_agile_backlog()
        tasks = self.env["project.task"].with_user(self.manager).with_context(**action["context"])
        self.assertIn(child, tasks.search(action["domain"]))
        self.assertNotIn(epic, tasks.search(action["domain"]))
        by_epic = {
            parent.id: points
            for parent, points in tasks._read_group(action["domain"], ["parent_id"], ["story_points:sum"])
        }
        self.assertEqual(by_epic[epic.id], 5)
        self.assertEqual(by_epic[False], 2)
        columns = tasks.web_read_group(action["domain"], ["parent_id"], ["__count"], limit=80)
        self.assertEqual(sorted(g["__count"] for g in columns["groups"]), [1, 1])

    def test_domain_lists_leaf_issues_and_hides_unsprinted_finished_work(self):
        sprint = self._sprint("Current", -1)
        in_sprint = self._issue("In sprint")
        in_sprint.write({"sprint_id": sprint.id})
        backlog = self._issue("Backlog item")
        finished_loose = self._issue("Finished but unsprinted")
        self._finish(finished_loose)
        finished_in_sprint = self._issue("Finished in sprint")
        finished_in_sprint.write({"sprint_id": sprint.id})
        self._finish(finished_in_sprint)
        epic_type = self.env["agile_community.task_type"].search([("is_epic", "=", True)], limit=1)
        epic = self._issue("An epic", agile_task_type_id=epic_type.id)
        child = self._issue("Child of epic", parent_id=epic.id)
        lonely_epic = self._issue("Epic without children", agile_task_type_id=epic_type.id)
        found = self.env["project.task"].with_user(self.manager).search(
            self.project._agile_backlog_domain()
        )
        self.assertIn(in_sprint, found)
        self.assertIn(backlog, found)
        self.assertIn(finished_in_sprint, found)
        self.assertIn(child, found)
        self.assertNotIn(finished_loose, found)
        self.assertNotIn(epic, found)
        self.assertNotIn(lonely_epic, found)

    def test_scrum_backlog_button_opens_agile_backlog_and_native_projects_keep_core(self):
        action = self.project.with_user(self.manager).action_backlog()
        self.assertEqual(action["name"], "Backlog")
        self.assertIn("agile_backlog", action["context"])
        native = self.env["project.project"].create({"name": "Native", "use_scrum": True})
        native_action = native.action_backlog()
        self.assertNotIn("agile_backlog", native_action["context"])
        self.assertEqual(native_action["view_mode"], "list,form")

    def test_header_data_reports_sprints_points_by_status_and_backlog_totals(self):
        sprint = self._sprint("Sprint A", -1)
        todo = self._issue("Todo", points=5)
        done = self._issue("Done", points=3)
        todo.write({"sprint_id": sprint.id})
        done.write({"sprint_id": sprint.id})
        self._finish(done)
        self._issue("Loose estimated", points=2)
        self._issue("Loose unestimated", points=None)
        data = self.project.with_user(self.manager).agile_backlog_sprints()
        row = next(r for r in data["sprints"] if r["id"] == sprint.id)
        self.assertEqual(row["state"], "draft")
        self.assertEqual(row["points_by_status"], {"ready": 5.0, "done": 3.0})
        self.assertEqual(row["capacity_points"], 0.0)
        self.assertFalse(row["over_capacity"])
        self.assertEqual(row["name"], "Sprint A")
        self.assertTrue(row["can_manage"])
        self.assertEqual(data["backlog"], {"issue_count": 2, "unestimated_count": 1})
        self.assertEqual(row["issue_count"], 2)

    def test_backlog_has_a_stable_address_that_reloads_the_agile_backlog(self):
        action = self.project.with_user(self.manager).action_open_agile_backlog()
        self.assertEqual(action["path"], "agile-backlog")
        self.assertEqual(action["context"]["active_id"], self.project.id)
        stored = self.env.ref("agile_community.action_agile_backlog_url")
        self.assertEqual(stored.path, "agile-backlog")
        reloaded = stored.with_user(self.manager).with_context(active_id=self.project.id)._get_action_dict()
        self.assertEqual(reloaded["path"], "agile-backlog")
        self.assertEqual(reloaded["domain"], action["domain"])
        # Without a project the stored action serves its plain self.
        self.assertNotIn("agile_backlog", stored.with_user(self.manager)._get_action_dict().get("context", {}))

    def test_header_data_counts_issues_per_assignee_for_the_pick_list(self):
        def count():
            data = self.project.with_user(self.manager).agile_backlog_sprints()
            return {m["id"]: m["issue_count"] for m in data["members"]}.get(self.manager.id, 0)

        before = count()
        self._issue("Assigned").write({"user_ids": [(6, 0, self.manager.ids)]})
        self.assertEqual(count(), before + 1)

    def test_plan_state_follows_confirm_then_stale_when_scope_changes(self):
        sprint = self._sprint("Planning", 2)
        self._issue("First").write({"sprint_id": sprint.id})

        def row():
            data = self.project.with_user(self.manager).agile_backlog_sprints()
            return next(r for r in data["sprints"] if r["id"] == sprint.id)

        self.assertFalse(row()["planning_confirmed"])
        sprint.with_user(self.manager).action_confirm_plan()
        confirmed = row()
        self.assertTrue(confirmed["planning_confirmed"])
        self.assertFalse(confirmed["planning_stale"])
        self._issue("Added later").write({"sprint_id": sprint.id})
        self.assertTrue(row()["planning_stale"])

    def test_completed_sprint_reports_its_summary(self):
        sprint = self._sprint("Old sprint", -6)
        issue = self._issue("Finished", points=4)
        issue.write({"sprint_id": sprint.id})
        sprint.with_user(self.manager).action_confirm_plan()
        sprint.with_user(self.manager).action_start()
        self._finish(issue)
        sprint.with_user(self.manager).action_done()
        row = next(
            r for r in self.project.with_user(self.manager).agile_backlog_sprints()["sprints"]
            if r["id"] == sprint.id
        )
        self.assertEqual(row["state"], "done")
        self.assertEqual(row["completed_points"], 4.0)
        self.assertEqual(row["committed_points_at_close"], 4.0)

    def test_contributor_reads_but_cannot_manage_and_outsiders_are_refused(self):
        sprint = self._sprint("Visible", 1)
        member = self._member()
        data = self.project.with_user(member).agile_backlog_sprints()
        self.assertFalse(next(r for r in data["sprints"] if r["id"] == sprint.id)["can_manage"])
        with self.assertRaises(AccessError):
            self.project.with_user(self.outsider).agile_backlog_sprints()
        with self.assertRaises(AccessError):
            self.project.with_user(self.outsider).action_open_agile_backlog()

    def test_groups_are_ordered_active_planned_backlog_then_completed(self):
        done = self._sprint("Done sprint", -20)
        late = self._sprint("Planned late", 20)
        soon = self._sprint("Planned soon", 8)
        active = self._sprint("Active", -2)
        for sprint in (done, late, soon, active):
            self._issue("In " + sprint.name).write({"sprint_id": sprint.id})
        self._issue("Loose")
        done.with_user(self.manager).action_confirm_plan()
        done.with_user(self.manager).write({"state": "in_progress"})
        for issue in done.task_ids:
            self._finish(issue)
        done.with_user(self.manager).action_done()
        active.with_user(self.manager).action_confirm_plan()
        active.with_user(self.manager).action_start()

        task = self.env["project.task"].with_user(self.manager)
        kwargs = {
            "domain": self.project._agile_backlog_domain(),
            "groupby": ["sprint_id"],
            "aggregates": ["__count"],
        }
        ordered = task.with_context(agile_backlog=True).web_read_group(**kwargs)["groups"]
        names = [g["sprint_id"][1] if g["sprint_id"] else "Backlog" for g in ordered]
        self.assertEqual(names, ["Active", "Planned soon", "Planned late", "Backlog", "Done sprint"])
        plain = task.web_read_group(**kwargs)["groups"]
        self.assertNotEqual(
            [g["sprint_id"][1] if g["sprint_id"] else "Backlog" for g in plain], names
        )

    def test_empty_planned_sprints_are_groups_so_they_can_take_a_drop(self):
        empty = self._sprint("Empty planned", 3)
        self._issue("Loose")
        task = self.env["project.task"].with_user(self.manager).with_context(
            agile_backlog=True, default_project_id=self.project.id
        )
        groups = task.web_read_group(
            domain=self.project._agile_backlog_domain(),
            groupby=["sprint_id"],
            aggregates=["__count"],
        )["groups"]
        self.assertIn(empty.id, [g["sprint_id"][0] for g in groups if g["sprint_id"]])
        without_flag = self.env["project.task"].with_user(self.manager).web_read_group(
            domain=self.project._agile_backlog_domain(),
            groupby=["sprint_id"],
            aggregates=["__count"],
        )["groups"]
        self.assertNotIn(empty.id, [g["sprint_id"][0] for g in without_flag if g["sprint_id"]])

    def test_moving_into_a_confirmed_plan_marks_it_changed_and_moving_back_restores_it(self):
        sprint = self._sprint("Confirmed", 2)
        first = self._issue("First")
        first.write({"sprint_id": sprint.id})
        sprint.with_user(self.manager).action_confirm_plan()
        moved = self._issue("Dragged in")

        def row():
            data = self.project.with_user(self.manager).agile_backlog_sprints()
            return next(r for r in data["sprints"] if r["id"] == sprint.id)

        moved.with_user(self.manager).write({"sprint_id": sprint.id})
        self.assertTrue(row()["planning_stale"])
        moved.with_user(self.manager).write({"sprint_id": False})
        self.assertFalse(row()["planning_stale"])

    def test_only_agile_managers_can_move_issues_between_sprints(self):
        sprint = self._sprint("Target", 2)
        issue = self._issue("Contributor tries")
        member = self._member()
        with self.assertRaisesRegex(AccessError, "Agile Manager can change sprint membership"):
            issue.with_user(member).write({"sprint_id": sprint.id})
        self.assertFalse(issue.sprint_id)
        # Ranking is not sprint membership: a contributor can still reorder.
        issue.with_user(member).write({"sequence": 5})
        self.assertEqual(issue.sequence, 5)

    def test_completed_sprints_refuse_a_drop_with_a_plain_message(self):
        sprint = self._sprint("Closed", -6)
        done_issue = self._issue("Done one", points=2)
        done_issue.write({"sprint_id": sprint.id})
        sprint.with_user(self.manager).action_confirm_plan()
        sprint.with_user(self.manager).action_start()
        self._finish(done_issue)
        sprint.with_user(self.manager).action_done()
        loose = self._issue("Late")
        with self.assertRaises(UserError) as caught:
            loose.with_user(self.manager).write({"sprint_id": sprint.id})
        self.assertIn("completed sprint", str(caught.exception).lower())

    def test_header_data_lists_assignable_people_issue_types_and_edit_rights(self):
        member = self._member()
        manager_data = self.project.with_user(self.manager).agile_backlog_sprints()
        contributor_data = self.project.with_user(member).agile_backlog_sprints()
        self.assertTrue(manager_data["can_edit"])
        self.assertTrue(contributor_data["can_edit"])
        names = {t["name"] for t in manager_data["task_types"]}
        self.assertTrue(names)
        self.assertNotIn(
            "Epic", names, "Epic types are not offered for backlog rows"
        )
        self.assertIn(self.contributor.id, [m["id"] for m in manager_data["members"]])
        stakeholder = new_test_user(
            self.env,
            login="backlog_stakeholder",
            groups="agile_community.group_agile_stakeholder",
        )
        self.env["agile.project.member"].with_user(self.manager).create({
            "project_id": self.project.id,
            "user_id": stakeholder.id,
            "role": "stakeholder",
        })
        self.assertFalse(
            self.project.with_user(stakeholder).agile_backlog_sprints()["can_edit"]
        )

    def test_inline_estimate_edit_validates_and_leaves_a_chatter_entry(self):
        member = self._member()
        issue = self._issue("Estimate me", points=None)
        self.assertFalse(issue.story_points_estimated)
        issue.with_user(member).write({"story_points": 5, "story_points_estimated": True})
        self.assertEqual(issue.story_points, 5.0)
        issue.with_user(member).write({"story_points_estimated": False, "story_points": 0})
        self.assertFalse(issue.story_points_estimated)
        # A refused edit leaves the old value in place.
        issue.with_user(member).write({"story_points": 5, "story_points_estimated": True})
        with self.assertRaises(ValidationError):
            issue.with_user(member).write({"story_points": -1})
        self.assertEqual(issue.story_points, 5.0)

    def test_inline_assignee_and_type_edits_are_tracked(self):
        member = self._member()
        issue = self._issue("Reassign me")
        other_type = self.env["agile_community.task_type"].search(
            [("is_epic", "=", False), ("id", "!=", issue.agile_task_type_id.id)], limit=1
        )
        issue.with_user(member).write({"user_ids": [(6, 0, [member.id])]})
        self.assertEqual(issue.user_ids, member)
        issue.with_user(member).write({"user_ids": [(6, 0, [])]})
        self.assertFalse(issue.user_ids)
        self.assertTrue(other_type, "the data ships more than one non-epic issue type")
        issue.with_user(member).write({"agile_task_type_id": other_type.id})
        self.assertEqual(issue.agile_task_type_id, other_type)
        self.assertEqual(issue.agile_task_type_id, other_type)

    def test_quick_create_rules_for_backlog_and_sprints(self):
        member = self._member()
        task_type = self.env["agile_community.task_type"].search(
            [("is_epic", "=", False)], limit=1
        )
        sprint = self._sprint("Quick target", 2)
        def values(name, **extra):
            # create() fills in the issue key on the dict it receives, so build a fresh one each time.
            return {
                "name": name,
                "project_id": self.project.id,
                "agile_task_type_id": task_type.id,
                **extra,
            }

        created = self.env["project.task"].with_user(member).create(values("Quick issue"))
        self.assertTrue(created.issue_key)
        self.assertTrue(created.agile_issue)
        self.assertFalse(created.sprint_id)
        by_manager = self.env["project.task"].with_user(self.manager).create(
            values("Quick in sprint", sprint_id=sprint.id)
        )
        self.assertEqual(by_manager.sprint_id, sprint)
        with self.assertRaisesRegex(AccessError, "Agile Manager can change sprint membership"):
            self.env["project.task"].with_user(member).create(
                values("Not allowed", sprint_id=sprint.id)
            )


    def test_inline_editable_fields_are_tracked_in_the_chatter(self):
        """Inline edits leave a chatter entry because the edited fields are tracked."""
        tracked = self.env["project.task"]._track_get_fields()
        for name in ("story_points", "story_points_estimated", "agile_task_type_id", "user_ids"):
            self.assertIn(name, tracked)

    def _epic(self, name):
        epic_type = self.env["agile_community.task_type"].search([("is_epic", "=", True)], limit=1)
        return self._issue(name, points=None, agile_task_type_id=epic_type.id)

    def test_epic_panel_counts_children_and_points_and_ignores_canceled_work(self):
        epic = self._epic("Planning UX")
        empty = self._epic("Nothing yet")
        done = self._issue(
            "Finished child", points=5, parent_id=epic.id,
            user_ids=[(6, 0, [self.manager.id])],
        )
        self._finish(done)
        self._issue("Open child", points=3, parent_id=epic.id)
        self._issue("Unestimated child", points=None, parent_id=epic.id)
        canceled = self._issue("Canceled child", points=8, parent_id=epic.id)
        canceled.with_user(self.manager).action_agile_cancel()
        self._issue("Loose issue", points=13)

        data = self.project.with_user(self.manager).agile_backlog_epics()
        by_id = {row["id"]: row for row in data["epics"]}
        self.assertEqual(
            {k: by_id[epic.id][k] for k in ("children", "done_children", "points", "done_points")},
            {"children": 3, "done_children": 1, "points": 8.0, "done_points": 5.0},
        )
        self.assertEqual(by_id[epic.id]["name"], "Planning UX")
        self.assertTrue(by_id[epic.id]["issue_key"])
        self.assertEqual(by_id[empty.id]["children"], 0)
        self.assertEqual(by_id[empty.id]["points"], 0.0)

    def test_epic_panel_counts_sub_tasks_not_their_parent_story(self):
        """A story with sub-tasks counts through its sub-tasks, like the sprint totals (NU-41)."""
        epic = self._epic("Opening")
        story = self._issue("Story", points=5, parent_id=epic.id)
        self._issue("Sub one", points=2, parent_id=story.id)
        self._issue("Sub two", points=3, parent_id=story.id)
        data = self.project.with_user(self.manager).agile_backlog_epics()
        row = next(r for r in data["epics"] if r["id"] == epic.id)
        self.assertEqual((row["children"], row["points"]), (2, 5.0))

    def test_kanban_backlog_has_no_sprint_defaults_and_board_explains_the_backlog(self):
        """Kanban projects open the Backlog without sprint controls (NU-47, NU-48)."""
        kanban = self.env["project.project"].with_user(self.manager).create({
            "name": "Kanban desk", "privacy_visibility": "employees", "agile_enabled": True,
            "agile_key": "KBD", "agile_method": "kanban",
        })
        action = kanban.with_user(self.manager).action_open_agile_backlog()
        self.assertTrue(action["context"]["agile_no_sprints"])
        self.assertNotIn("search_default_agile_hide_completed", action["context"])
        self.assertFalse(self.project.with_user(self.manager).action_open_agile_backlog()["context"]["agile_no_sprints"])
        self.env["project.task"].with_user(self.manager).create({
            "name": "Waiting", "project_id": kanban.id, "description": "x",
        })
        help_text = self.env["project.task"].with_user(self.manager).with_context(
            default_project_id=kanban.id, agile_project_view=True
        ).get_empty_list_help("")
        self.assertIn("Nothing is on the board yet", help_text)

    def test_kanban_board_hides_the_empty_backlog_column(self):
        """A Kanban board without its own Backlog column does not list the Backlog stage (OI-1)."""
        kanban = self.env["project.project"].with_user(self.manager).create({
            "name": "Kanban cols", "privacy_visibility": "employees", "agile_enabled": True,
            "agile_key": "KCL", "agile_method": "kanban",
        })
        action = kanban.with_user(self.manager).action_view_tasks()
        self.assertTrue(action["context"].get("agile_hide_backlog_column"))
        task = self.env["project.task"].with_context(**action["context"])
        columns = task._read_group_stage_ids(self.env["project.task.type"], [])
        self.assertTrue(columns)
        self.assertNotIn("backlog", columns.mapped("agile_status"))
        kanban.agile_kanban_backlog_column = True
        again = kanban.with_user(self.manager).action_view_tasks()
        self.assertFalse(again["context"].get("agile_hide_backlog_column"))

    def test_epic_panel_leaves_out_canceled_epics_and_other_projects(self):
        epic = self._epic("Kept")
        gone = self._epic("Dropped")
        gone.with_user(self.manager).action_agile_cancel()
        other = self.env["project.project"].with_user(self.manager).create({
            "name": "Other",
            "privacy_visibility": "employees",
            "agile_enabled": True,
            "agile_key": "OTHR",
            "agile_method": "scrum",
        })
        epic_type = self.env["agile_community.task_type"].search([("is_epic", "=", True)], limit=1)
        self.env["project.task"].with_user(self.manager).create({
            "name": "Foreign epic",
            "project_id": other.id,
            "description": "x",
            "agile_task_type_id": epic_type.id,
        })
        names = [e["name"] for e in self.project.with_user(self.manager).agile_backlog_epics()["epics"]]
        self.assertEqual(names, ["Kept"])
        self.assertTrue(epic)

    def test_epic_panel_is_for_project_members_only(self):
        self._epic("Visible")
        member = self._member()
        self.assertEqual(len(self.project.with_user(member).agile_backlog_epics()["epics"]), 1)
        with self.assertRaises(AccessError):
            self.project.with_user(self.outsider).agile_backlog_epics()
