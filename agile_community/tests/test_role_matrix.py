from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, new_test_user


class TestAgileRoleMatrix(TransactionCase):
    """A-002: read/write/export per Agile role on issues, sprints and releases."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin_manager = new_test_user(
            cls.env, login="rm_manager", groups="project.group_project_manager"
        )
        cls.contributor = new_test_user(
            cls.env, login="rm_contributor", groups="project.group_project_user"
        )
        cls.reviewer = new_test_user(
            cls.env, login="rm_reviewer", groups="agile_community.group_agile_reviewer"
        )
        cls.stakeholder = new_test_user(
            cls.env,
            login="rm_stakeholder",
            groups="agile_community.group_agile_stakeholder",
        )
        cls.portal = new_test_user(
            cls.env, login="rm_portal", groups="base.group_portal"
        )
        cls.project = cls.env["project.project"].with_user(cls.admin_manager).create({
            "name": "Role matrix",
            "privacy_visibility": "employees",
            "agile_enabled": True,
            "agile_key": "ROLEM",
            "allow_milestones": True,
        })
        # Enabling Agile seeds every existing project user as a contributor, so
        # the outsider must be created after the project to be a non-member.
        cls.unrelated = new_test_user(
            cls.env, login="rm_unrelated", groups="project.group_project_user"
        )
        members = cls.env["agile.project.member"].with_user(cls.admin_manager)
        for user, role in (
            (cls.contributor, "contributor"),
            (cls.reviewer, "reviewer"),
            (cls.stakeholder, "stakeholder"),
        ):
            existing = members.search([
                ("project_id", "=", cls.project.id), ("user_id", "=", user.id),
            ])
            if existing:
                existing.write({"role": role})
            else:
                members.create({
                    "project_id": cls.project.id, "user_id": user.id, "role": role,
                })
        cls.task = cls.env["project.task"].with_user(cls.admin_manager).create({
            "name": "Matrix issue",
            "project_id": cls.project.id,
            "description": "A short matrix-test description.",
            "agile_issue": True,
        })
        cls.sprint = cls.env["project.sprint"].with_user(cls.admin_manager).create({
            "name": "Matrix sprint",
            "project_id": cls.project.id,
            "date_start": "2026-09-01",
            "date_end": "2026-09-14",
        })
        cls.release = cls.env["project.version"].with_user(cls.admin_manager).create({
            "name": "Matrix 1.0", "project_id": cls.project.id,
        })

    def _can(self, user, record, op):
        rec = record.with_user(user)
        try:
            if op == "read":
                rec.read(["display_name"])
            elif op == "write":
                rec.write({"name": rec.sudo().name})
            elif op == "export":
                rec.export_data(["id", "display_name"])
            return True
        except (AccessError, UserError):
            return False

    def test_matrix(self):
        # user -> {record: (read, write)}
        expected = {
            self.admin_manager: {"task": (1, 1), "sprint": (1, 1), "release": (1, 1)},
            self.contributor: {"task": (1, 1), "sprint": (1, 0), "release": (1, 0)},
            self.reviewer: {"task": (1, 1), "sprint": (1, 0), "release": (1, 0)},
            self.stakeholder: {"task": (1, 0), "sprint": (1, 0), "release": (1, 0)},
            self.unrelated: {"task": (0, 0), "sprint": (0, 0), "release": (0, 0)},
            self.portal: {"task": (0, 0), "sprint": (0, 0), "release": (0, 0)},
        }
        records = {"task": self.task, "sprint": self.sprint, "release": self.release}
        for user, per_record in expected.items():
            for name, (can_read, can_write) in per_record.items():
                with self.subTest(user=user.login, record=name):
                    self.assertEqual(
                        self._can(user, records[name], "read"), bool(can_read), "read"
                    )
                    self.assertEqual(
                        self._can(user, records[name], "write"), bool(can_write), "write"
                    )
                    if not can_read:
                        self.assertFalse(
                            self._can(user, records[name], "export"), "export leak"
                        )

    def test_enabling_manager_can_work_in_the_project(self):
        owner = new_test_user(
            self.env, login="rm_owner", groups="project.group_project_manager"
        )
        project = self.env["project.project"].with_user(owner).create({
            "name": "Native then Agile",
            "privacy_visibility": "employees",
            "user_id": self.contributor.id,
        })
        project.with_user(self.admin_manager).write({
            "agile_enabled": True, "agile_key": "ENAB",
        })
        member = project.with_user(self.admin_manager).agile_member_ids.filtered(
            lambda m: m.user_id == self.admin_manager
        )
        self.assertEqual(member.role, "manager")
        issue = self.env["project.task"].with_user(self.admin_manager).create({
            "name": "First issue",
            "project_id": project.id,
            "description": "Created right after enabling Agile.",
            "agile_issue": True,
        })
        self.assertTrue(issue.issue_key)
