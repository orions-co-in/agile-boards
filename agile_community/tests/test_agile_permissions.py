from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user


class TestAgilePermissions(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        group = "project.group_project_user"
        cls.manager = new_test_user(cls.env, login="pm_manager", groups="project.group_project_manager", name="Mia Manager")
        cls.contributor = new_test_user(cls.env, login="pm_contrib", groups=group, name="Cora Contributor")
        cls.reviewer = new_test_user(cls.env, login="pm_reviewer", groups=group, name="Rae Reviewer")
        cls.stakeholder = new_test_user(cls.env, login="pm_stake", groups=group, name="Sam Stakeholder")
        cls.outsider = new_test_user(cls.env, login="pm_outsider", groups=group, name="Otto Outsider")
        cls.project = cls.env["project.project"].with_user(cls.manager).create({
            "name": "Permission project", "privacy_visibility": "employees", "agile_enabled": True,
            "agile_key": "PRM", "agile_method": "scrum",
        })
        Member = cls.env["agile.project.member"].sudo()
        Member.search([("project_id", "=", cls.project.id), ("user_id", "=", cls.outsider.id)]).unlink()
        for user, role in ((cls.contributor, "contributor"), (cls.reviewer, "reviewer"), (cls.stakeholder, "stakeholder")):
            member = Member.search([("project_id", "=", cls.project.id), ("user_id", "=", user.id)])
            if member:
                member.role = role
            else:
                Member.create({"project_id": cls.project.id, "user_id": user.id, "role": role})

    def _issue(self, status="review", **vals):
        issue = self.env["project.task"].with_user(self.manager).create({
            "name": "Issue", "project_id": self.project.id, "description": "Do it.",
            "user_ids": [Command.set([self.contributor.id])], **vals,
        })
        steps = ["mark_ready", "start", "send_review"]
        order = ["backlog", "ready", "progress", "review"]
        for step in steps[: order.index(status)]:
            getattr(issue.with_user(self.manager), f"action_agile_{step}")()
        return issue

    def _flags(self, issue, flag):
        users = {"manager": self.manager, "contributor": self.contributor, "reviewer": self.reviewer, "stakeholder": self.stakeholder}
        return {role for role, user in users.items() if issue.with_user(user)[flag]}

    def _scheme(self, scheme):
        self.project.with_user(self.manager).write({"agile_permission_scheme": scheme})

    def test_buttons_follow_the_scheme_for_every_role(self):
        review = self._issue("review")
        backlog = self._issue("backlog")
        expected = {
            "standard": ({"manager", "reviewer"}, {"manager", "reviewer"}, {"manager", "contributor"}, {"manager"}),
            "open": ({"manager", "contributor", "reviewer"}, {"manager", "contributor", "reviewer"}, {"manager", "contributor", "reviewer"}, {"manager", "contributor"}),
            "strict": ({"manager"}, {"manager", "reviewer"}, {"manager", "contributor"}, {"manager"}),
        }
        for scheme, (complete, back, ready, cancel) in expected.items():
            self._scheme(scheme)
            for task in (review, backlog):
                task.invalidate_recordset()
            self.assertEqual(self._flags(review, "can_agile_complete"), complete, scheme)
            self.assertEqual(self._flags(review, "can_agile_return"), back, scheme)
            self.assertEqual(self._flags(backlog, "can_agile_mark_ready"), ready, scheme)
            self.assertEqual(self._flags(backlog, "can_agile_cancel"), cancel, scheme)

    def test_actions_are_refused_or_allowed_by_the_scheme(self):
        issue = self._issue("review")
        with self.assertRaises(UserError):
            issue.with_user(self.contributor).action_agile_complete()
        self._scheme("open")
        issue.with_user(self.contributor).action_agile_complete()
        self.assertEqual(issue.agile_status, "done")
        self._scheme("strict")
        second = self._issue("review")
        with self.assertRaises(UserError):
            second.with_user(self.reviewer).action_agile_complete()
        second.with_user(self.manager).action_agile_complete()

    def test_sprint_membership_and_roadmap_dates_follow_the_scheme(self):
        sprint = self.env["project.sprint"].with_user(self.manager).create({
            "name": "S", "project_id": self.project.id, "date_start": "2026-10-01",
            "date_option": "custom", "date_end": "2026-10-14"})
        issue = self._issue("backlog")
        with self.assertRaises(AccessError):
            issue.with_user(self.contributor).write({"sprint_id": sprint.id})
        with self.assertRaises(AccessError):
            issue.with_user(self.contributor).write({"agile_planned_start": "2026-10-02"})
        self._scheme("open")
        issue.with_user(self.contributor).write({"sprint_id": sprint.id, "agile_planned_start": "2026-10-02"})
        self.assertEqual(issue.sprint_id, sprint)
        with self.assertRaises(AccessError):
            issue.with_user(self.stakeholder).write({"agile_planned_start": "2026-10-03"})

    def test_only_a_manager_changes_the_scheme_and_it_is_logged(self):
        with self.assertRaises(AccessError):
            self.project.with_user(self.contributor).write({"agile_permission_scheme": "open"})
        self._scheme("open")
        notes = self.project.sudo().message_ids.mapped("body")
        self.assertTrue(any("from Standard to Open" in (body or "") for body in notes))

    def test_permissions_page_is_for_managers(self):
        Page = self.env["agile.permissions"]
        with self.assertRaises(AccessError):
            Page.with_user(self.contributor).permissions_data(self.project.id)
        data = Page.with_user(self.manager).permissions_data(self.project.id)
        self.assertEqual(data["scheme"], "standard")
        self.assertEqual([s["key"] for s in data["schemes"]], ["standard", "open", "strict", "custom"])
        self.assertTrue(data["matrix"]["strict"])
        self.assertEqual(Page.with_user(self.manager).set_scheme(self.project.id, "strict")["scheme"], "strict")
        with self.assertRaises(UserError):
            Page.with_user(self.manager).set_scheme(self.project.id, "nope")
        action = self.project.with_user(self.manager).action_open_agile_permissions()
        self.assertEqual(action["tag"], "agile_community.permissions")
        # The sidebar and breadcrumb find the project from the context.
        self.assertEqual(action["context"]["default_project_id"], self.project.id)
        with self.assertRaises(AccessError):
            self.project.with_user(self.contributor).action_open_agile_permissions()

    # ---- restricted issues -------------------------------------------------------

    def _can_open(self, issue, user):
        return bool(self.env["project.task"].with_user(user).search([("id", "=", issue.id)]))

    def test_restricted_issue_is_visible_only_to_the_allowed(self):
        issue = self._issue("backlog", user_ids=[Command.clear()])
        self.assertTrue(all(self._can_open(issue, u) for u in (self.contributor, self.reviewer, self.stakeholder)))
        issue.with_user(self.manager).write({
            "agile_restricted": True, "agile_visible_user_ids": [Command.set([self.reviewer.id])]})
        self.assertTrue(self._can_open(issue, self.manager))
        self.assertTrue(self._can_open(issue, self.reviewer), "named")
        self.assertFalse(self._can_open(issue, self.contributor))
        self.assertFalse(self._can_open(issue, self.stakeholder))
        self.assertFalse(self._can_open(issue, self.outsider))
        issue.with_user(self.manager).write({"user_ids": [Command.set([self.contributor.id])]})
        self.assertTrue(self._can_open(issue, self.contributor), "assignee")

    def test_the_reporter_always_sees_and_may_restrict_their_issue(self):
        issue = self.env["project.task"].with_user(self.contributor).create({
            "name": "Mine", "project_id": self.project.id, "description": "x", "user_ids": [Command.clear()]})
        issue.with_user(self.contributor).write({"agile_restricted": True})
        self.assertTrue(self._can_open(issue, self.contributor))
        self.assertFalse(self._can_open(issue, self.reviewer))
        with self.assertRaises(AccessError):
            self._issue("backlog").with_user(self.reviewer).write({"agile_restricted": True})

    def test_visible_people_must_be_on_the_team(self):
        issue = self._issue("backlog")
        with self.assertRaises(ValidationError):
            issue.with_user(self.manager).write({
                "agile_restricted": True, "agile_visible_user_ids": [Command.set([self.outsider.id])]})

    def test_restricting_removes_followers_who_cannot_see_it(self):
        issue = self._issue("backlog", user_ids=[Command.clear()])
        issue.sudo().message_subscribe(partner_ids=[self.reviewer.partner_id.id, self.stakeholder.partner_id.id])
        issue.with_user(self.manager).write({
            "agile_restricted": True, "agile_visible_user_ids": [Command.set([self.reviewer.id])]})
        followers = issue.sudo().message_partner_ids
        self.assertIn(self.reviewer.partner_id, followers)
        self.assertNotIn(self.stakeholder.partner_id, followers)
        issue.sudo().message_subscribe(partner_ids=[self.stakeholder.partner_id.id])
        self.assertNotIn(self.stakeholder.partner_id, issue.sudo().message_partner_ids)

    def test_subtasks_start_restricted_like_their_parent(self):
        parent = self._issue("backlog", user_ids=[Command.clear()])
        parent.with_user(self.manager).write({
            "agile_restricted": True, "agile_visible_user_ids": [Command.set([self.reviewer.id])]})
        subtask_type = self.env.ref("agile_community.agile_task_type_task")
        child = self.env["project.task"].with_user(self.manager).create({
            "name": "Sub", "project_id": self.project.id, "parent_id": parent.id,
            "agile_task_type_id": subtask_type.id, "description": "x", "user_ids": [Command.clear()]})
        self.assertTrue(child.agile_restricted)
        self.assertEqual(child.agile_visible_user_ids, self.reviewer)

    def test_turning_the_restriction_off_is_logged_and_shows_everyone(self):
        issue = self._issue("backlog", user_ids=[Command.clear()])
        issue.with_user(self.manager).write({"agile_restricted": True})
        self.assertFalse(self._can_open(issue, self.reviewer))
        issue.with_user(self.manager).write({"agile_restricted": False})
        self.assertTrue(self._can_open(issue, self.reviewer))
        bodies = " ".join(issue.sudo().message_ids.mapped("body"))
        self.assertIn("removed the restriction", bodies)

    def test_reports_do_not_leak_restricted_issues(self):
        issue = self._issue("backlog", user_ids=[Command.clear()])
        issue.with_user(self.manager).write({"agile_restricted": True})
        found = self.env["project.task"].with_user(self.contributor).search([("project_id", "=", self.project.id)])
        self.assertNotIn(issue, found)
        self.assertEqual(self.env["project.task"].with_user(self.contributor).search_count(
            [("project_id", "=", self.project.id), ("id", "=", issue.id)]), 0)


class TestApiRecipe(TransactionCase):
    """docs/API_RECIPE.md names these methods and arguments; keep the guide true."""

    def test_documented_calls_exist_with_the_documented_arguments(self):
        import inspect

        Task = self.env["project.task"]
        for name in (
            "action_agile_mark_ready", "action_agile_start", "action_agile_send_review",
            "action_agile_return", "action_agile_complete", "action_agile_reopen", "action_agile_cancel",
        ):
            params = list(inspect.signature(getattr(Task, name)).parameters)
            self.assertEqual(params, [], f"{name} takes only ids")
        self.assertEqual(list(inspect.signature(Task.write).parameters), ["vals"])
        self.assertEqual(list(inspect.signature(Task.search_read).parameters)[:3], ["domain", "fields", "offset"])
        self.assertIn("vals_list", inspect.signature(Task.create).parameters)
        self.assertIn("kwargs", inspect.signature(Task.message_post).parameters)  # body, message_type and subtype_xmlid are keywords
        for field in ("issue_key", "agile_status", "story_points", "sprint_id", "user_ids"):
            self.assertIn(field, Task._fields)
        self.assertIn("agile_key", self.env["project.project"]._fields)


class TestCustomPermissionScheme(TestAgilePermissions):
    """T-1142: a project edits the Contributor and Reviewer columns of its own scheme, within safe limits."""

    def _custom(self, **grants):
        full = {"forward": ["contributor"], "return": ["reviewer"], "complete": ["reviewer"], "lifecycle": [],
                "sprint_membership": [], "roadmap_dates": []}
        full.update(grants)
        self.project.with_user(self.manager).agile_set_custom_permissions(full)

    def test_a_new_project_stays_standard_with_nothing_saved(self):
        fresh = self.env["project.project"].with_user(self.manager).create(
            {"name": "Fresh", "agile_enabled": True, "agile_key": "FRS", "agile_method": "scrum"}
        )
        self.assertEqual(fresh.agile_permission_scheme, "standard")
        self.assertFalse(fresh.agile_permission_custom)

    def test_custom_starts_where_standard_is(self):
        review = self._issue("review")
        self._custom()
        review.invalidate_recordset()
        self.assertEqual(self._flags(review, "can_agile_complete"), {"manager", "reviewer"})
        self.assertEqual(self._flags(review, "can_agile_return"), {"manager", "reviewer"})

    def test_a_grant_adds_the_move_and_a_withdrawal_removes_it(self):
        review = self._issue("review")
        self._custom(complete=["contributor"], **{"return": []})
        review.invalidate_recordset()
        self.assertEqual(self._flags(review, "can_agile_complete"), {"manager", "contributor"})
        self.assertEqual(self._flags(review, "can_agile_return"), {"manager"})
        review.with_user(self.contributor).action_agile_complete()
        self.assertEqual(review.agile_status, "done")
        with self.assertRaises(UserError):
            self._issue("review").with_user(self.reviewer).action_agile_return()

    def test_sprint_and_roadmap_actions_follow_the_grants(self):
        project = self.project
        self.assertFalse(project._agile_allows("roadmap_dates", self.contributor))
        self._custom(roadmap_dates=["contributor"], sprint_membership=["reviewer"])
        self.assertTrue(project._agile_allows("roadmap_dates", self.contributor))
        self.assertFalse(project._agile_allows("roadmap_dates", self.reviewer))
        self.assertTrue(project._agile_allows("sprint_membership", self.reviewer))
        self.assertTrue(project._agile_allows("sprint_membership", self.manager))

    def test_managers_always_may_and_stakeholders_never(self):
        self._custom(forward=[], complete=[], lifecycle=[])
        review = self._issue("review")
        self.assertEqual(self._flags(review, "can_agile_complete"), {"manager"})
        self._custom(forward=["contributor", "reviewer"], complete=["contributor", "reviewer"], lifecycle=["contributor", "reviewer"])
        review.invalidate_recordset()
        self.assertNotIn("stakeholder", self._flags(review, "can_agile_complete"))
        self.assertIn("manager", self._flags(review, "can_agile_complete"))

    def test_only_contributor_and_reviewer_columns_of_listed_actions_can_change(self):
        project = self.project.with_user(self.manager)
        for bad in ({"complete": ["manager"]}, {"complete": ["stakeholder"]}, {"releases": ["contributor"]}, {"complete": "reviewer"}, []):
            with self.assertRaises(UserError, msg=str(bad)):
                project.agile_set_custom_permissions(bad)
        self.assertEqual(self.project.agile_permission_scheme, "standard")

    def test_only_a_manager_edits_and_the_change_is_audited(self):
        with self.assertRaises(AccessError):
            self.project.with_user(self.contributor).agile_set_custom_permissions({"forward": ["contributor"]})
        self._custom()
        before = self.project.message_ids
        self._custom(lifecycle=["contributor"])
        self.assertTrue(self.project.message_ids - before)

    def test_the_page_lists_editable_rows_with_the_saved_grants(self):
        self._custom(complete=["contributor"])
        data = self.env["agile.permissions"].with_user(self.manager).permissions_data(self.project.id)
        self.assertEqual(data["scheme"], "custom")
        rows = {row["key"]: row for row in data["matrix"]["custom"]}
        self.assertTrue(rows["complete"]["editable"])
        self.assertEqual(rows["complete"]["grants"], ["contributor"])
        self.assertEqual(rows["complete"]["roles"], ["Project Manager", "Contributor"])
        self.assertFalse(rows[None]["editable"])
        self.assertFalse(data["matrix"]["standard"][0]["editable"])
