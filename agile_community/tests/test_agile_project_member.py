from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user


class TestAgileProjectMember(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(
            cls.env,
            login="agile_member_manager",
            groups="project.group_project_manager",
        )
        cls.project = cls.env["project.project"].with_user(cls.manager).create({
            "name": "Agile team security",
            "agile_enabled": True,
            "agile_key": "TEAMSEC",
        })
        cls.contributor = new_test_user(
            cls.env,
            login="agile_member_contributor",
            groups="project.group_project_user",
        )

    def _assign_role(self, project, user, role):
        Member = self.env["agile.project.member"].with_user(self.manager)
        member = Member.search([
            ("project_id", "=", project.id),
            ("user_id", "=", user.id),
        ], limit=1)
        if member:
            member.write({"role": role})
            return member
        return Member.create({
            "project_id": project.id,
            "user_id": user.id,
            "role": role,
        })

    def test_context_flag_cannot_bypass_project_manager_check(self):
        late_user = new_test_user(
            self.env,
            login="agile_member_late_user",
            groups="project.group_project_user",
        )
        membership = self.env["agile.project.member"].with_user(self.manager).create({
            "project_id": self.project.id,
            "user_id": late_user.id,
            "role": "contributor",
        })

        with self.assertRaises(AccessError):
            membership.with_user(self.contributor).with_context(
                agile_role_seed=True
            ).write({"role": "manager"})

        self.assertEqual(membership.role, "contributor")

    def test_technical_superuser_keeps_access_without_changing_member_roles(self):
        technical_user = self.env.ref("base.user_root")

        self.assertEqual(
            self.project._agile_role_for_user(technical_user),
            "manager",
        )
        self.assertEqual(
            self.project._agile_role_for_user(self.contributor),
            "none",
        )

    def test_membership_audit_actor_cannot_be_supplied_by_client(self):
        late_user = new_test_user(
            self.env,
            login="agile_member_audit_user",
            groups="project.group_project_user",
        )
        membership = self.env["agile.project.member"].with_user(self.manager).create({
            "project_id": self.project.id,
            "user_id": late_user.id,
            "role": "contributor",
            "assigned_by_id": self.contributor.id,
        })

        self.assertEqual(membership.assigned_by_id, self.manager)

    def test_project_scoped_manager_can_manage_team_with_audited_actor(self):
        self.project.write({"privacy_visibility": "employees"})
        self._assign_role(self.project, self.contributor, "manager")
        teammate = new_test_user(
            self.env,
            login="agile_member_audit_teammate",
            groups="project.group_project_user",
        )
        membership = self.env["agile.project.member"].with_user(
            self.contributor
        ).create({
            "project_id": self.project.id,
            "user_id": teammate.id,
            "role": "contributor",
        })
        audit_message = self.env["mail.message"].sudo().search([
            ("model", "=", "project.project"),
            ("res_id", "=", self.project.id),
            ("body", "ilike", "%s was added to the Agile team" % teammate.name),
        ], order="id desc", limit=1)

        self.assertTrue(membership)
        self.assertEqual(audit_message.author_id, self.contributor.partner_id)

    def test_team_members_must_have_native_project_level_access(self):
        outsider = new_test_user(
            self.env,
            login="agile_member_private_outsider",
            groups="project.group_project_user",
        )
        unrelated_manager = new_test_user(
            self.env,
            login="agile_member_unrelated_project_manager",
            groups="project.group_project_manager",
        )
        private_project = self.env["project.project"].with_user(self.manager).create({
            "name": "Follower-only Agile project",
            "privacy_visibility": "followers",
            "agile_enabled": True,
            "agile_key": "FOLLOW",
        })

        self.assertFalse(
            self.env["project.project"].with_user(outsider).search(
                [("id", "=", private_project.id)]
            )
        )
        self.assertFalse(
            self.env["agile.project.member"].sudo().search([
                ("project_id", "=", private_project.id),
                ("user_id", "=", outsider.id),
            ])
        )
        self.assertFalse(
            self.env["agile.project.member"].sudo().search([
                ("project_id", "=", private_project.id),
                ("user_id", "=", unrelated_manager.id),
            ])
        )
        with self.assertRaises(ValidationError):
            self.env["agile.project.member"].with_user(self.manager).create({
                "project_id": private_project.id,
                "user_id": outsider.id,
                "role": "contributor",
            })

    def test_unrelated_project_manager_cannot_read_another_agile_roster(self):
        unrelated_manager = new_test_user(
            self.env,
            login="agile_member_unrelated_roster_manager",
            groups="project.group_project_manager",
        )
        other_project = self.env["project.project"].with_user(
            unrelated_manager
        ).create({
            "name": "Another manager's Agile project",
            "agile_enabled": True,
            "agile_key": "OTHERTEAM",
        })

        self.assertTrue(other_project.with_user(self.manager).has_access("read"))
        self.assertTrue(self.env["agile.project.member"].sudo().search_count([
            ("project_id", "=", other_project.id),
        ]))
        self.assertFalse(self.env["agile.project.member"].with_user(
            self.manager
        ).search([
            ("project_id", "=", other_project.id),
        ]))

    def test_agile_configuration_rows_follow_current_allowed_companies(self):
        other_company = self.env["res.company"].sudo().create({
            "name": "Agile other company",
        })
        self.manager.write({
            "company_ids": [(4, other_company.id)],
        })
        manager_projects = self.env["project.project"].with_user(
            self.manager
        ).with_context(allowed_company_ids=self.manager.company_ids.ids)
        project = manager_projects.create({
            "name": "Agile company boundary",
            "company_id": other_company.id,
            "privacy_visibility": "employees",
            "agile_enabled": True,
            "agile_key": "COMPANYB",
        })
        component = self.env["agile.project.component"].with_user(
            self.manager
        ).with_context(allowed_company_ids=self.manager.company_ids.ids).create({
            "name": "Private company component",
            "project_id": project.id,
        })
        quick_filter = self.env["agile.project.quick.filter"].with_user(
            self.manager
        ).with_context(allowed_company_ids=self.manager.company_ids.ids).create({
            "name": "Private company filter",
            "project_id": project.id,
            "filter_type": "unassigned",
        })

        self.manager.write({
            "company_ids": [(3, other_company.id)],
        })
        current_company_context = {"allowed_company_ids": [self.env.company.id]}
        self.assertFalse(self.env["agile.project.component"].with_user(
            self.manager
        ).with_context(**current_company_context).search([
            ("id", "=", component.id),
        ]))
        self.assertFalse(self.env["agile.project.quick.filter"].with_user(
            self.manager
        ).with_context(**current_company_context).search([
            ("id", "=", quick_filter.id),
        ]))

    def test_role_project_domain_rechecks_current_native_visibility(self):
        self.project.write({"privacy_visibility": "employees"})
        self._assign_role(self.project, self.contributor, "reviewer")
        revoked_project = self.env["project.project"].with_user(self.manager).create({
            "name": "Review access revoked",
            "privacy_visibility": "employees",
            "agile_enabled": True,
            "agile_key": "REVOKE",
        })
        self._assign_role(revoked_project, self.contributor, "reviewer")
        revoked_project.write({"privacy_visibility": "followers"})

        self.assertFalse(
            revoked_project.with_user(self.contributor).has_access("read")
        )
        visible_ids = self.env["agile.project.member"].with_user(
            self.contributor
        )._readable_project_ids_for_roles(["reviewer", "manager"])
        self.assertIn(self.project.id, visible_ids)
        self.assertNotIn(revoked_project.id, visible_ids)

    def test_stale_agile_manager_cannot_mutate_wip_limits(self):
        self.project.write({"privacy_visibility": "employees"})
        self._assign_role(self.project, self.contributor, "manager")
        backlog = self.project.type_ids.filtered(
            lambda stage: stage.agile_status == "backlog"
        )[:1]
        limit = self.env["agile.project.wip.limit"].with_user(
            self.contributor
        ).create({
            "project_id": self.project.id,
            "stage_id": backlog.id,
            "wip_limit": 5,
        })
        audit_message = self.env["mail.message"].sudo().search([
            ("model", "=", "project.project"),
            ("res_id", "=", self.project.id),
            ("body", "ilike", "WIP limit was added"),
        ], order="id desc", limit=1)
        self.assertEqual(audit_message.author_id, self.contributor.partner_id)
        self.project.write({"privacy_visibility": "followers"})

        self.assertFalse(self.project.with_user(self.contributor).has_access("read"))
        with self.assertRaises(AccessError):
            limit.with_user(self.contributor).write({"wip_limit": 6})
        with self.assertRaises(AccessError):
            self.env["agile.project.wip.limit"].with_user(
                self.contributor
            ).create({
                "project_id": self.project.id,
                "stage_id": backlog.id,
                "wip_limit": 6,
            })

    def test_stale_agile_manager_cannot_manage_team_after_project_access_revoked(self):
        self.project.write({"privacy_visibility": "employees"})
        membership = self._assign_role(
            self.project, self.contributor, "manager"
        )
        replacement = new_test_user(
            self.env,
            login="agile_member_replacement_manager",
            groups="project.group_project_manager",
        )
        self.project.write({"privacy_visibility": "followers"})

        self.assertFalse(self.project.with_user(self.contributor).has_access("read"))
        with self.assertRaises(AccessError):
            membership.with_user(self.contributor).write({"role": "reviewer"})
        with self.assertRaises(AccessError):
            membership.with_user(self.contributor).unlink()
        with self.assertRaises(AccessError):
            self.env["agile.project.member"].with_user(self.contributor).create({
                "project_id": self.project.id,
                "user_id": replacement.id,
                "role": "contributor",
            })

    def test_stale_agile_manager_cannot_manage_sprint_after_project_access_revoked(self):
        self.project.write({"privacy_visibility": "employees"})
        self._assign_role(self.project, self.contributor, "manager")
        self.project.write({"privacy_visibility": "followers"})

        sprint_model = self.env["project.sprint"].with_user(self.contributor)
        self.assertFalse(self.project.with_user(self.contributor).has_access("read"))
        self.assertFalse(
            sprint_model._is_project_manager_for_project(self.project)
        )
        with self.assertRaisesRegex(AccessError, "native Odoo Project access"):
            sprint_model._check_project_manager_role(project=self.project)

    def test_stale_agile_manager_cannot_convert_native_tasks(self):
        project = self.env["project.project"].with_user(self.manager).create({
            "name": "Legacy conversion access",
            "privacy_visibility": "employees",
        })
        task = self.env["project.task"].with_user(self.manager).create({
            "name": "Existing native task",
            "project_id": project.id,
        })
        project.with_user(self.manager).write({
            "agile_enabled": True,
            "agile_key": "LEGACY",
        })
        self._assign_role(project, self.contributor, "manager")
        self.assertFalse(task.agile_issue)
        wizard = self.env["agile_community.issue_migration_wizard"].with_user(
            self.contributor
        ).create({
            "project_id": project.id,
            "task_ids": [Command.set([task.id])],
            "issue_type_id": self.env.ref(
                "agile_community.agile_task_type_task"
            ).id,
        })

        project.with_user(self.manager).write({"privacy_visibility": "followers"})
        self.assertFalse(project.with_user(self.contributor).has_access("read"))
        with self.assertRaises(AccessError):
            wizard.action_convert()

        self.assertFalse(task.agile_issue)

    def test_inactive_user_cannot_be_added_to_agile_team(self):
        inactive_user = new_test_user(
            self.env,
            login="agile_member_inactive_user",
            groups="project.group_project_user",
        )
        inactive_user.active = False

        with self.assertRaises(ValidationError):
            self.env["agile.project.member"].with_user(self.manager).create({
                "project_id": self.project.id,
                "user_id": inactive_user.id,
                "role": "contributor",
            })

    def test_inactive_project_owner_is_not_seeded_as_agile_manager(self):
        inactive_owner = new_test_user(
            self.env,
            login="agile_member_inactive_owner",
            groups="project.group_project_manager",
        )
        inactive_owner.active = False
        project = self.env["project.project"].create({
            "name": "Inactive owner Agile project",
            "user_id": inactive_owner.id,
            "agile_enabled": True,
            "agile_key": "INACTOWN",
        })

        self.assertFalse(
            self.env["agile.project.member"].sudo().search([
                ("project_id", "=", project.id),
                ("user_id", "=", inactive_owner.id),
            ])
        )

    def test_native_project_versions_keep_existing_internal_visibility(self):
        native_project = self.env["project.project"].create({
            "name": "Unchanged native project",
        })
        version = self.env["project.version"].create({
            "name": "Native release",
            "project_id": native_project.id,
        })
        visible_versions = self.env["project.version"].with_user(
            self.contributor
        ).search([("id", "=", version.id)])

        self.assertEqual(visible_versions, version)
