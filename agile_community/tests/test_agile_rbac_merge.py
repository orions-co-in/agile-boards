from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user
from .pro_guard import needs_pro


class TestAgileRbacMerge(TransactionCase):
    """Odoo groups set a ceiling (implicit manager); team rows stay the control for everyone else."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.owner = new_test_user(env, login="rbac_owner", groups="project.group_project_manager")
        cls.project = env["project.project"].with_user(cls.owner).create(
            {"name": "RBAC", "agile_enabled": True, "agile_key": "RBAC", "agile_method": "kanban"}
        )
        Member = env["agile.project.member"].sudo()
        cls.team = {}
        for role in ("manager", "contributor", "reviewer", "stakeholder"):
            user = new_test_user(env, login="rbac_%s" % role, groups="project.group_project_user")
            cls.project.sudo().message_subscribe(partner_ids=user.partner_id.ids)
            Member.create({"project_id": cls.project.id, "user_id": user.id, "role": role})
            cls.team[role] = user
        cls.outsider = new_test_user(env, login="rbac_outsider", groups="project.group_project_user")
        cls.project_admin = new_test_user(env, login="rbac_padmin", groups="project.group_project_manager")
        cls.odoo_admin = new_test_user(env, login="rbac_sysadmin", groups="base.group_system")
        cls.agile_admin = new_test_user(
            env, login="rbac_agadmin", groups="agile_community.group_agile_admin"
        )
        cls.issue = env["project.task"].with_user(cls.owner).create(
            {"name": "Visible", "project_id": cls.project.id}
        )

    def _issues(self, user):
        return self.env["project.task"].with_user(user).search([("project_id", "=", self.project.id)])

    def test_resolver_matrix(self):
        project = self.project
        self.assertEqual(project._agile_access(self.odoo_admin), ("manager", "odoo_admin"))
        self.assertEqual(project._agile_access(self.agile_admin), ("manager", "odoo_admin"))
        for role, user in self.team.items():
            self.assertEqual(project._agile_access(user), (role, "team"))
        self.assertEqual(project._agile_access(self.outsider), ("none", "none"))
        # Q1: Odoo Project Administrator is not promoted.
        self.assertEqual(project._agile_access(self.project_admin), ("none", "none"))

    def test_followers_only_project_still_needs_a_follow(self):
        # Decision: the ceiling does not override Odoo's own project privacy.
        self.project.sudo().privacy_visibility = "followers"
        self.assertFalse(self._issues(self.agile_admin))
        self.project.sudo().message_subscribe(partner_ids=self.agile_admin.partner_id.ids)
        self.assertIn(self.issue, self._issues(self.agile_admin))

    def test_not_agile_project_gives_none(self):
        plain = self.env["project.project"].create({"name": "Plain"})
        self.assertEqual(plain._agile_access(self.odoo_admin), ("none", "none"))

    def test_batch_and_single_resolver_agree(self):
        other = self.env["project.project"].with_user(self.owner).create(
            {"name": "RBAC2", "agile_enabled": True, "agile_key": "RBTWO"}
        )
        projects = (self.project | other).sudo()
        users = [self.odoo_admin, self.agile_admin, self.outsider, self.project_admin, *self.team.values()]
        for user in users:
            batch = projects._agile_access_by_project(user)
            for project in projects:
                self.assertEqual(batch[project.id], project._agile_access(user), user.login)
            roles = self.env["project.task"].with_user(user)._agile_roles_by_project(projects.ids)
            for project in projects:
                self.assertEqual(roles.get(project.id, "none"), project._agile_access(user)[0], user.login)

    def test_issue_visibility(self):
        for user in (self.odoo_admin, self.agile_admin, *self.team.values()):
            self.assertIn(self.issue, self._issues(user), user.login)
        for user in (self.outsider, self.project_admin):
            self.assertFalse(self._issues(user), user.login)

    def test_restricted_issue_visible_to_implicit_manager(self):
        self.issue.sudo().agile_restricted = True
        self.assertIn(self.issue, self._issues(self.odoo_admin))
        self.assertIn(self.issue, self._issues(self.agile_admin))
        self.assertNotIn(self.issue, self._issues(self.team["contributor"]))
        self.assertIn(self.issue, self._issues(self.team["manager"]))

    def test_implicit_manager_can_manage_team_and_is_not_a_row(self):
        newbie = new_test_user(self.env, login="rbac_newbie", groups="project.group_project_user")
        self.project.sudo().message_subscribe(partner_ids=newbie.partner_id.ids)
        Member = self.env["agile.project.member"]
        for admin in (self.odoo_admin, self.agile_admin):
            member = Member.with_user(admin).create(
                {"project_id": self.project.id, "user_id": newbie.id, "role": "contributor"}
            )
            member.with_user(admin).write({"role": "reviewer"})
            member.with_user(admin).unlink()
        self.assertFalse(Member.sudo().search([
            ("project_id", "=", self.project.id),
            ("user_id", "in", (self.odoo_admin | self.agile_admin).ids),
        ]))

    def test_last_manager_guard_counts_team_rows_only(self):
        manager_row = self.env["agile.project.member"].sudo().search(
            [("project_id", "=", self.project.id), ("role", "=", "manager")]
        )
        with self.assertRaises(ValidationError):
            manager_row.with_user(self.odoo_admin).write({"role": "contributor"})
        with self.assertRaises(ValidationError):
            manager_row.with_user(self.agile_admin).unlink()

    def test_team_roles_still_limit_non_admins(self):
        Member = self.env["agile.project.member"]
        for user in (self.team["contributor"], self.outsider, self.project_admin):
            with self.assertRaises(AccessError):
                Member.with_user(user).create(
                    {"project_id": self.project.id, "user_id": self.outsider.id, "role": "contributor"}
                )

    def test_removing_the_group_removes_access(self):
        user = new_test_user(self.env, login="rbac_temp", groups="project.group_project_user,agile_community.group_agile_admin")
        self.assertEqual(self.project._agile_access(user), ("manager", "odoo_admin"))
        self.assertIn(self.issue, self._issues(user))
        user.sudo().write({"group_ids": [(3, self.env.ref("agile_community.group_agile_admin").id)]})
        self.assertEqual(self.project._agile_access(user), ("none", "none"))
        self.assertFalse(self._issues(user))

    @needs_pro("agile.agent.call")
    def test_agents_do_not_inherit_the_ceiling(self):
        agent = new_test_user(self.env, login="rbac_agent", groups="project.group_project_user")
        agent.sudo().write({"agile_is_agent": True, "agile_agent_level": "work"})
        group = self.env.ref("agile_community.group_agile_admin")
        with self.assertRaises(ValidationError):
            agent.sudo().write({"group_ids": [(4, group.id)]})

    def test_sidebar_says_where_access_comes_from(self):
        data = self.project.with_user(self.odoo_admin).agile_sidebar_data()
        self.assertTrue(data["enabled"])
        self.assertEqual(data["access_source"], "odoo_admin")
        self.assertIn("Odoo administrator", data["access_label"])
        data = self.project.with_user(self.agile_admin).agile_sidebar_data()
        self.assertIn("Agile administrator", data["access_label"])
        data = self.project.with_user(self.team["reviewer"]).agile_sidebar_data()
        self.assertEqual(data["access_source"], "team")
        self.assertIn("Team", data["access_label"])
        self.assertFalse(self.project.with_user(self.outsider).agile_sidebar_data()["enabled"])

    @needs_pro("agile.audit")
    def test_audit_marks_actions_through_the_ceiling(self):
        self.project.with_user(self.odoo_admin)._agile_audit("team", "Changed something")
        self.project.with_user(self.team["manager"])._agile_audit("team", "Changed something else")
        texts = self.env["agile.audit"].sudo().search([("project_id", "=", self.project.id)]).mapped("text")
        self.assertIn("Changed something (via Odoo administrator)", texts)
        self.assertIn("Changed something else", texts)

    def test_review_queue_projects_include_ceiling(self):
        Member = self.env["agile.project.member"]
        self.assertIn(
            self.project.id,
            Member.with_user(self.agile_admin)._readable_project_ids_for_roles(["reviewer", "manager"]),
        )
        self.assertNotIn(
            self.project.id,
            Member.with_user(self.outsider)._readable_project_ids_for_roles(["reviewer", "manager"]),
        )
