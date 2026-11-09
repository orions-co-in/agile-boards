from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, new_test_user


class TestAgileSidebar(TransactionCase):
    """N-101 to N-104 and B-401 to B-405: project sidebar and Jira-style board."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, login="sb_manager", groups="project.group_project_manager")
        cls.contributor = new_test_user(cls.env, login="sb_contrib", groups="project.group_project_user")
        cls.outsider = new_test_user(cls.env, login="sb_outsider", groups="project.group_project_user")
        cls.project = cls._project("SBA", "scrum")
        cls.kanban = cls._project("SBK", "kanban")
        cls.today = fields.Date.context_today(cls.project)
        member = cls.env["agile.project.member"].sudo().search([
            ("project_id", "=", cls.project.id), ("user_id", "=", cls.contributor.id)])
        if member:
            member.role = "contributor"
        else:
            cls.env["agile.project.member"].with_user(cls.manager).create({
                "project_id": cls.project.id, "user_id": cls.contributor.id, "role": "contributor",
            })

    @classmethod
    def _project(cls, key, method):
        project = cls.env["project.project"].with_user(cls.manager).create({
            "name": f"Sidebar {key}", "privacy_visibility": "employees", "agile_enabled": True,
            "agile_key": key, "agile_method": method,
        })
        cls.env["agile.project.member"].sudo().search([
            ("project_id", "=", project.id), ("user_id", "=", cls.outsider.id)]).unlink()
        return project

    def _issue(self, name, **extra):
        values = {"name": name, "project_id": self.project.id, "description": "Sidebar issue.", "story_points": 2}
        values.update(extra)
        return self.env["project.task"].with_user(self.manager).create(values)

    def _sprint(self, name, start=0):
        day = self.today + timedelta(days=start)
        return self.env["project.sprint"].with_user(self.manager).create({
            "name": name, "project_id": self.project.id, "date_start": day,
            "date_option": "custom", "date_end": day + timedelta(days=6),
        })

    # ---- N-101 / N-104: sidebar data and actions ----

    def test_manager_sees_every_entry(self):
        data = self.project.with_user(self.manager).agile_sidebar_data()
        self.assertTrue(data["enabled"])
        self.assertEqual(
            data["entries"],
            ["summary", "roadmap"] + (["capacity"] if "agile.capacity" in self.env else [])
            + ["backlog", "board", "sprints", "mine", "reports", "releases", "components", "settings"],
        )
        self.assertEqual(data["key"], "SBA")

    def test_contributor_has_no_configuration_entries(self):
        data = self.project.with_user(self.contributor).agile_sidebar_data()
        self.assertNotIn("components", data["entries"])
        self.assertNotIn("settings", data["entries"])
        with self.assertRaises(AccessError):
            self.project.with_user(self.contributor).agile_sidebar_action("settings")

    def test_kanban_project_has_no_sprints_entry(self):
        data = self.kanban.with_user(self.manager).agile_sidebar_data()
        self.assertNotIn("sprints", data["entries"])

    def test_outsider_and_non_agile_project_get_no_sidebar(self):
        self.assertEqual(self.project.with_user(self.outsider).agile_sidebar_data(), {"enabled": False})
        plain = self.env["project.project"].with_user(self.manager).create({"name": "Plain"})
        self.assertEqual(plain.with_user(self.manager).agile_sidebar_data(), {"enabled": False})

    def test_counts_cover_unplanned_backlog_and_blocked(self):
        sprint = self._sprint("S1")
        self._issue("Unplanned one")
        self._issue("Unplanned two")
        self._issue("Planned", sprint_id=sprint.id)
        blocked = self._issue("Blocked", sprint_id=sprint.id)
        blocked.write({"agile_blocked": True, "agile_block_reason": "Waiting"})
        counts = self.project.with_user(self.manager).agile_sidebar_data()["counts"]
        self.assertEqual(counts["backlog"], 2)
        self.assertEqual(counts["blocked"], 1)

    def test_every_entry_opens_an_action_with_views(self):
        project = self.project.with_user(self.manager)
        for entry in project.agile_sidebar_data()["entries"]:
            action = project.agile_sidebar_action(entry)
            self.assertTrue(action.get("type"), entry)
            if action["type"] == "ir.actions.act_window":
                self.assertTrue(action.get("views"), entry)
        self.assertEqual(project.agile_sidebar_action("board")["name"], "Board")

    def test_unknown_entry_is_refused(self):
        with self.assertRaises(AccessError):
            self.project.with_user(self.manager).agile_sidebar_action("nope")

    # ---- N-103: landing and menu ----

    def test_card_lands_on_summary_for_team_and_board_for_others(self):
        action = self.project.with_user(self.manager).agile_open_landing()
        self.assertEqual(action["tag"], "agile_community.summary")
        plain = self.env["project.project"].with_user(self.manager).create({"name": "Plain 2"})
        self.assertEqual(plain.with_user(self.manager).agile_open_landing()["res_model"], "project.task")

    def test_menu_lists_only_the_users_agile_projects(self):
        action = self.env["project.project"].with_user(self.outsider).agile_open_menu()
        visible = self.env["project.project"].browse(action["domain"][0][2])
        self.assertNotIn(self.project, visible)
        action = self.env["project.project"].with_user(self.manager).agile_open_menu()
        self.assertEqual(action["type"], "ir.actions.act_window")
        self.assertIn(self.project.id, action["domain"][0][2])

    # ---- B-401 / B-402: board columns ----

    def test_scrum_board_hides_backlog_and_canceled_columns(self):
        project = self.project.with_user(self.manager)
        action = project.action_view_tasks()
        context = action["context"]
        self.assertTrue(context["agile_scrum_mode"])
        self.assertIn(("stage_id.agile_status", "!=", "backlog"), action["domain"])
        task = self.env["project.task"].with_user(self.manager).with_context(**context)
        stages = self.env["project.task.type"].search([("project_ids", "=", project.id)])
        shown = task._read_group_stage_ids(stages, [])
        self.assertEqual(set(shown.mapped("agile_status")), {"ready", "progress", "review", "done"})
        with_canceled = task.with_context(agile_show_canceled=True)._read_group_stage_ids(stages, [])
        self.assertIn("canceled", with_canceled.mapped("agile_status"))

    def test_kanban_board_keeps_every_column(self):
        """Backlog issues are hidden unless the project asks for a Backlog column, so the empty column goes too (OI-1)."""
        project = self.kanban.with_user(self.manager)
        stages = self.env["project.task.type"].search([("project_ids", "=", project.id)])

        def columns():
            context = project.action_view_tasks()["context"]
            task = self.env["project.task"].with_user(self.manager).with_context(**context)
            return task._read_group_stage_ids(stages, []).mapped("agile_status")

        self.assertNotIn("backlog", columns())
        self.assertIn("progress", columns())
        project.sudo().agile_kanban_backlog_column = True
        self.assertIn("backlog", columns())

    def test_ready_stage_is_named_to_do(self):
        stage = self.env["project.task.type"].search([
            ("project_ids", "=", self.project.id), ("agile_status", "=", "ready")], limit=1)
        self.assertEqual(stage.name, "To Do")

    # ---- B-403: moving into and out of a sprint ----

    def test_moving_into_a_sprint_makes_the_issue_to_do_and_back(self):
        sprint = self._sprint("S2")
        issue = self._issue("Move me")
        self.assertEqual(issue.agile_status, "backlog")
        issue.with_user(self.manager).write({"sprint_id": sprint.id})
        self.assertEqual(issue.agile_status, "ready")
        issue.with_user(self.manager).write({"sprint_id": False})
        self.assertEqual(issue.agile_status, "backlog")

    def test_issue_created_in_a_sprint_starts_as_to_do(self):
        sprint = self._sprint("S3")
        self.assertEqual(self._issue("Born planned", sprint_id=sprint.id).agile_status, "ready")

    def test_work_in_progress_keeps_its_status_when_leaving_a_sprint(self):
        sprint = self._sprint("S4")
        issue = self._issue("Busy", sprint_id=sprint.id, user_ids=[(6, 0, [self.manager.id])])
        issue.with_user(self.manager).action_agile_start()
        issue.with_user(self.manager).write({"sprint_id": False})
        self.assertEqual(issue.agile_status, "progress")

    # ---- B-405: empty board ----

    def test_board_without_active_sprint_explains_how_to_start_one(self):
        self._issue("Anything")
        help_text = self.env["project.task"].with_user(self.manager).with_context(
            default_project_id=self.project.id, agile_scrum_mode=True, agile_project_view=True
        ).get_empty_list_help("")
        self.assertIn("No sprint is active", help_text)

    def test_the_board_action_carries_the_scrum_help(self):
        """E2E-013: the help the board opens with is the Scrum one, not the stored action's."""
        self._issue("Anything")
        action = self.project.with_user(self.manager).action_view_tasks()
        self.assertIn("No sprint is active", action["help"])

    # ---- Q-602: empty board and labels ----

    def test_board_with_a_sprint_but_no_match_explains_the_filters(self):
        sprint = self._sprint("S5")
        self._issue("In it", sprint_id=sprint.id)
        sprint.with_user(self.manager).action_confirm_plan()
        sprint.with_user(self.manager).action_start()
        help_text = self.env["project.task"].with_user(self.manager).with_context(
            default_project_id=self.project.id, agile_scrum_mode=True, agile_project_view=True
        ).get_empty_list_help("")
        self.assertIn("No issues match the filters", help_text)
        self.assertIn("Mine", help_text)

    def test_wizard_labels_and_widgets(self):
        arch = self.env["ir.ui.view"].sudo().search([
            ("model", "=", "agile_community.release_notes_wizard"), ("type", "=", "form")], limit=1).arch
        self.assertIn("CopyClipboardText", arch)
        arch = self.env["ir.ui.view"].sudo().search([
            ("model", "=", "project.sprint.close"), ("type", "=", "form")], limit=1).arch
        self.assertIn("Unfinished issues", arch)

    # ---- V-701: every project button opens for a manager who is not an Odoo administrator ----

    def test_every_project_action_opens_for_a_project_manager(self):
        project = self.project.with_user(self.manager)
        methods = (
            "action_manage_agile_team", "action_manage_agile_issue_types", "action_manage_agile_components",
            "action_view_unconverted_agile_tasks", "action_open_agile_roadmap_page", "action_view_agile_roadmap",
            "action_view_agile_unscheduled_issues", "action_view_agile_roadmap_epics",
            "action_agile_view_preferences", "action_manage_agile_quick_filters", "action_open_agile_workflows",
            "action_open_agile_automation", "action_open_agile_filters", "action_open_agile_backlog",
            "action_open_agile_overview", "action_open_agile_summary", "action_open_agile_reports",
            "action_open_agile_your_work", "action_sprints", "action_view_tasks",
        )
        for method in methods:
            if not hasattr(project, method):
                continue  # a screen of agile_pro, which is not installed
            action = getattr(project, method)()
            self.assertIsInstance(action, dict, method)
            self.assertTrue(action.get("type"), method)

    # ---- Settings tab: Dashboard button, tool descriptions, backlog outside the sprint ----

    def _project_form_arch(self):
        view = self.env["project.project"].with_user(self.manager).get_view(
            self.env.ref("project.edit_project").id, "form")
        return view["arch"]

    def test_dashboard_button_is_hidden_on_agile_projects(self):
        from lxml import etree
        arch = etree.fromstring(self._project_form_arch())
        button = arch.xpath("//button[@name='project_update_all_action']")[0]
        self.assertIn("agile_enabled", button.get("invisible"))

    def test_every_settings_tool_says_what_it_does(self):
        from lxml import etree
        arch = etree.fromstring(self._project_form_arch())
        rows = arch.xpath("//div[contains(@class, 'o_agile_tool')]")
        names = {row.get("name") for row in rows}
        expected = {
            "agile_tool_team", "agile_tool_types", "agile_tool_components", "agile_tool_prepare",
            "agile_tool_workflows", "agile_tool_automation", "agile_tool_filters", "agile_tool_roadmap",
            "agile_tool_timeline", "agile_tool_unscheduled", "agile_tool_epics",
            "agile_tool_prefs", "agile_tool_quick",
        }
        if "agile.automation.rule" not in self.env:
            expected.discard("agile_tool_automation")
        self.assertEqual(expected - names, set())
        for row in rows:
            self.assertTrue(row.xpath(".//button"), row.get("name"))
            self.assertTrue(row.xpath(".//span[@class='o_agile_tool_help']/text()"), row.get("name"))

    def test_default_workflow_has_the_two_backlog_moves(self):
        workflow = self.env["agile.workflow"].search([("project_id", "=", self.project.id), ("is_default", "=", True)])
        moves = {
            (t.name, t.from_status_id.category, t.to_status_id.category) for t in workflow.transition_ids
        }
        self.assertIn(("Plan into sprint", "backlog", "ready"), moves)
        self.assertIn(("Back to backlog", "ready", "backlog"), moves)
        self.assertNotIn("Mark ready", {t.name for t in workflow.transition_ids})

    # ---- Create dialog: ask for Agile when the project is created ----

    def test_create_dialog_offers_agile_and_suggests_a_key(self):
        from odoo.tests import Form
        form = Form(
            self.env["project.project"].with_user(self.manager),
            view="project.project_project_view_form_simplified_footer",
        )
        form.name = "Orions Project"
        form.agile_enabled = True
        self.assertEqual(form.agile_key, "ORI")
        form.agile_method = "kanban"
        project = form.save()
        self.assertTrue(project.agile_enabled)
        self.assertEqual((project.agile_key, project.agile_method), ("ORI", "kanban"))
        action = project.with_user(self.manager).agile_open_landing()
        self.assertEqual(action["tag"], "agile_community.summary")

    def test_create_dialog_without_agile_makes_a_plain_project(self):
        from odoo.tests import Form
        form = Form(
            self.env["project.project"].with_user(self.manager),
            view="project.project_project_view_form_simplified_footer",
        )
        form.name = "Plain dialog project"
        project = form.save()
        self.assertFalse(project.agile_enabled)

    def test_suggested_key_skips_taken_keys(self):
        Project = self.env["project.project"]
        self.assertEqual(Project._agile_suggest_key("Sidebar Alpha"), "SID")
        self.assertEqual(Project._agile_suggest_key("SBA of things"), "SBA2")
        self.assertEqual(Project._agile_suggest_key("7"), "PRJ")
        self.assertEqual(Project._agile_suggest_key("123 Plan"), "PLA")

    def test_owner_pick_lists_come_from_a_field_the_form_can_read(self):
        # The old domain walked project_id.agile_member_ids in the browser and failed on a new record.
        component = self.env["agile.project.component"].create(
            {"name": "Owner list", "project_id": self.project.id}
        )
        members = self.project.agile_member_ids.user_id
        self.assertTrue(members)
        self.assertEqual(component.member_user_ids, members)
        quick_filter = self.env["agile.project.quick.filter"].create(
            {"name": "Owner filter", "project_id": self.project.id, "filter_type": "unassigned"}
        )
        self.assertEqual(quick_filter.member_user_ids, members)

    def _start(self, sprint):
        issue = self._issue(f"In {sprint.name}", sprint_id=sprint.id)
        sprint.with_user(self.manager).action_confirm_plan()
        sprint.with_user(self.manager).action_start()
        return issue

    def test_second_active_sprint_needs_the_project_switch(self):
        first, second = self._sprint("Multi A"), self._sprint("Multi B", 1)
        self._start(first)
        self._issue("In Multi B", sprint_id=second.id)
        second.with_user(self.manager).action_confirm_plan()
        with self.assertRaises(UserError):
            second.with_user(self.manager).action_start()
        self.project.allow_multiple_active_sprints = True
        second.with_user(self.manager).action_start()
        self.assertEqual(self.project._agile_active_sprints(), first | second)
        # Back to one at a time is refused while two run, allowed once one is completed.
        with self.assertRaises(UserError):
            self.project.allow_multiple_active_sprints = False

    def test_summary_follows_all_active_sprints_or_a_chosen_one(self):
        self.project.allow_multiple_active_sprints = True
        first, second = self._sprint("Sum A"), self._sprint("Sum B", 1)
        self._start(first)
        self._start(second)
        project = self.project.with_user(self.manager)
        both = project.agile_summary_data()
        self.assertEqual([row["name"] for row in both["active_sprints"]], ["Sum A", "Sum B"])
        self.assertEqual(sum(row["count"] for row in both["status"]), 2)
        one = project.agile_summary_data(sprint_id=second.id)
        self.assertEqual(sum(row["count"] for row in one["status"]), 1)
        self.assertEqual(one["sprint"]["id"], second.id)
        self.assertEqual(both["sprint"]["id"], first.id)

    def test_sidebar_and_board_name_several_active_sprints(self):
        self.project.allow_multiple_active_sprints = True
        for name, offset in (("Side A", 0), ("Side B", 1)):
            self._start(self._sprint(name, offset))
        data = self.project.with_user(self.manager).agile_sidebar_data()
        self.assertEqual(data["sprint"], "2 active sprints")
        options = self.project.with_user(self.manager).agile_board_options()
        self.assertEqual([row["name"] for row in options["sprints"]], ["Side A", "Side B"])
        self.project.with_user(self.manager).agile_save_board_options(filters=["sprint:%d" % options["sprints"][0]["id"]])
        action = self.project.with_user(self.manager).action_view_tasks()
        self.assertEqual(action["context"]["search_default_agile_active_sprint"], 1)
        self.assertNotIn("default_sprint_id", action["context"])
