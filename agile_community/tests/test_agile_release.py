from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user


class TestAgileRelease(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(
            cls.env, login="release_manager", groups="project.group_project_manager"
        )
        cls.contributor = new_test_user(
            cls.env, login="release_contributor", groups="project.group_project_user"
        )
        cls.reviewer = new_test_user(
            cls.env, login="release_reviewer", groups="agile_community.group_agile_reviewer"
        )
        cls.project = cls.env["project.project"].create({
            "name": "Release project",
            "privacy_visibility": "employees",
            "user_id": cls.manager.id,
            "agile_enabled": True,
            "agile_key": "RELQA",
            "allow_milestones": True,
        })
        cls.other_project = cls.env["project.project"].create({
            "name": "Other release project",
            "privacy_visibility": "employees",
            "user_id": cls.manager.id,
            "agile_enabled": True,
            "agile_key": "RELQB",
        })

    def _release(self, name="1.0", project=None, **extra):
        values = {"name": name, "project_id": (project or self.project).id}
        values.update(extra)
        return self.env["project.version"].with_user(self.manager).create(values)

    def _issue(self, name="Release issue", project=None):
        return self.env["project.task"].create({
            "name": name,
            "project_id": (project or self.project).id,
            "description": "A short release-test description.",
        })

    def _complete(self, task):
        manager_task = task.with_user(self.manager)
        manager_task.action_agile_mark_ready()
        manager_task.action_agile_start()
        manager_task.action_agile_send_review()
        task.with_user(self.reviewer).action_agile_complete()

    def test_oca_version_foundation_still_works_for_normal_projects(self):
        native = self.env["project.project"].create({"name": "Native Project"})
        version = self.env["project.version"].with_user(self.contributor).create({
            "name": "1.0",
            "project_id": native.id,
        })
        task = self.env["project.task"].with_user(self.contributor).create({
            "name": "Native task",
            "project_id": native.id,
            "version_id": version.id,
        })
        self.assertFalse(version.is_agile_release)
        self.assertEqual(task.version_id, version)

    def test_only_manager_can_create_or_release_agile_version(self):
        with self.assertRaises(AccessError):
            self.env["project.version"].with_user(self.contributor).create({
                "name": "Forbidden",
                "project_id": self.project.id,
            })
        release = self._release()
        with self.assertRaises(AccessError):
            release.with_user(self.contributor).write({"name": "Member edit"})
        with self.assertRaises(AccessError):
            release.with_user(self.contributor).action_release()
        self.assertEqual(release.state, "planned")

    def test_manager_can_update_a_planned_release_target_date(self):
        release = self._release(release_date="2026-09-28")
        release.with_user(self.manager).write({"release_date": "2026-10-01"})
        self.assertEqual(str(release.release_date), "2026-10-01")

    def test_two_releases_cannot_share_a_name_in_one_project(self):
        self._release("Twin 1.0")
        with self.assertRaises(ValidationError):
            self._release(" twin 1.0 ")
        # Another project may reuse the name, and an archived release frees it.
        self._release("Twin 1.0", project=self.other_project)
        old = self._release("Twin 2.0")
        old.active = False
        self._release("Twin 2.0")

    def test_release_visibility_follows_private_project_membership(self):
        private_project = self.env["project.project"].create({
            "name": "Private releases",
            "privacy_visibility": "followers",
            "user_id": self.manager.id,
            "agile_enabled": True,
            "agile_key": "RELPRIV",
        })
        release = self._release(project=private_project)
        visible_to_member = self.env["project.version"].with_user(self.contributor).search_count([
            ("id", "=", release.id),
        ])
        visible_to_manager = self.env["project.version"].with_user(self.manager).search_count([
            ("id", "=", release.id),
        ])
        self.assertFalse(visible_to_member)
        self.assertEqual(visible_to_manager, 1)

    def test_member_cannot_assign_a_hidden_cross_project_release(self):
        private_project = self.env["project.project"].create({
            "name": "Hidden target",
            "privacy_visibility": "followers",
            "user_id": self.manager.id,
            "agile_enabled": True,
            "agile_key": "RELHIDE",
        })
        hidden_release = self._release(project=private_project)
        task = self._issue()
        with self.assertRaisesRegex(ValidationError, "same project"):
            task.with_user(self.contributor).write({"version_id": hidden_release.id})

    def test_archived_release_cannot_receive_new_issue_targets(self):
        release = self._release()
        release.with_user(self.manager).write({"active": False})
        task = self._issue()
        with self.assertRaisesRegex(ValidationError, "Archived fix versions"):
            task.write({"version_id": release.id})

    def test_issue_and_milestone_must_belong_to_release_project(self):
        release = self._release()
        foreign_release = self._release("Other", project=self.other_project)
        task = self._issue()
        with self.assertRaisesRegex(ValidationError, "same project"):
            task.write({"version_id": foreign_release.id})

        foreign_milestone = self.env["project.milestone"].create({
            "name": "Other milestone",
            "project_id": self.other_project.id,
        })
        with self.assertRaisesRegex(ValidationError, "same project"):
            with self.env.cr.savepoint():
                release.write({"milestone_id": foreign_milestone.id})

    def test_readiness_counts_done_open_and_canceled_and_lists_blockers(self):
        release = self._release()
        opened = self._issue("Open")
        done = self._issue("Done")
        canceled = self._issue("Canceled")
        done.write({"version_id": release.id})
        opened.write({"version_id": release.id})
        canceled.write({"version_id": release.id})
        self._complete(done)
        canceled.with_user(self.manager).action_agile_cancel()

        self.assertEqual(release.issue_count, 3)
        self.assertEqual(release.done_issue_count, 1)
        self.assertEqual(release.open_issue_count, 1)
        self.assertEqual(release.canceled_issue_count, 1)
        self.assertFalse(release.is_ready)
        blockers = release.action_view_release_blockers()
        self.assertIn(("stage_id.agile_status", "not in", ["done", "canceled"]), blockers["domain"])
        self.assertIn(("project_id.agile_enabled", "=", True), blockers["domain"])

    def test_done_and_canceled_only_release_is_ready_and_milestone_is_independent(self):
        milestone = self.env["project.milestone"].create({
            "name": "Release milestone",
            "project_id": self.project.id,
        })
        release = self._release(milestone_id=milestone.id)
        done = self._issue("Done")
        canceled = self._issue("Canceled")
        done.write({"version_id": release.id})
        canceled.write({"version_id": release.id})
        self._complete(done)
        canceled.with_user(self.manager).action_agile_cancel()

        self.assertTrue(release.is_ready)
        release.with_user(self.manager).action_release()
        self.assertEqual(release.state, "released")
        self.assertEqual(release.released_by_id, self.manager)
        self.assertTrue(release.released_at)
        self.assertFalse(milestone.is_reached)
        self.assertEqual(release.audit_ids.mapped("event_type"), ["created", "released"])

    def test_open_work_does_not_hide_blockers_when_release_is_confirmed(self):
        release = self._release()
        blocker = self._issue()
        blocker.write({"version_id": release.id})
        action = release.with_user(self.manager).action_release()
        self.assertEqual(action["params"]["type"], "warning")
        self.assertTrue(action["params"]["sticky"])
        self.assertEqual(release.open_issue_count, 1)
        self.assertEqual(release.audit_ids[-1].new_values["open_issues"], 1)

    def test_release_dialog_counts_open_issues_and_can_move_them(self):
        # NU-12: Continue? alone did not say how many were open or offer a way out.
        release = self._release()
        next_release = self._release(name="Next version")
        blocker = self._issue("Open one")
        blocker.write({"version_id": release.id})
        action = release.with_user(self.manager).action_agile_open_release_confirm()
        wizard = self.env["agile.release.confirm"].with_user(self.manager).browse(action["res_id"])
        self.assertEqual(wizard.open_count, 1)
        self.assertIn("Open one", wizard.open_list)
        wizard.handling = "move"
        with self.assertRaises(UserError):
            wizard.action_confirm()
        wizard.target_version_id = next_release
        wizard.action_confirm()
        self.assertEqual(release.state, "released")
        self.assertEqual(blocker.version_id, next_release)
        self.assertEqual(release.open_issue_count, 0)

    def test_release_dialog_can_leave_open_issues_in_place(self):
        release = self._release()
        blocker = self._issue("Stays")
        blocker.write({"version_id": release.id})
        action = release.with_user(self.manager).action_agile_open_release_confirm()
        wizard = self.env["agile.release.confirm"].with_user(self.manager).browse(action["res_id"])
        wizard.action_confirm()
        self.assertEqual(release.state, "released")
        self.assertEqual(blocker.version_id, release)

    def test_released_record_and_issue_target_are_immutable_without_correction(self):
        release = self._release()
        task = self._issue()
        task.write({"version_id": release.id})
        release.with_user(self.manager).action_release()
        with self.assertRaisesRegex(UserError, "correction"):
            release.with_user(self.manager).write({"release_date": "2026-10-01"})
        with self.assertRaisesRegex(UserError, "correction"):
            task.write({"version_id": False})
        with self.assertRaises(UserError):
            release.with_user(self.manager).unlink()

    def test_correction_wizard_requires_reason_and_audits_metadata_changes(self):
        release = self._release()
        release.with_user(self.manager).action_release()
        wizard = self.env["agile_community.release_correction_wizard"].with_user(self.manager).create({
            "release_id": release.id,
            "reason": "The agreed date changed.",
            "release_date": "2026-10-01",
        })
        wizard.action_apply()
        self.assertEqual(str(release.release_date), "2026-10-01")
        correction = release.audit_ids.filtered(lambda row: row.event_type == "corrected")
        self.assertEqual(correction.reason, "The agreed date changed.")
        self.assertEqual(correction.previous_values["target_date"], False)
        self.assertEqual(correction.new_values["target_date"], "2026-10-01")
        with self.assertRaises(AccessError):
            self.env["agile_community.release_correction_wizard"].with_user(self.contributor).create({
                "release_id": release.id,
                "reason": "Not authorized",
            })

    def test_issue_membership_correction_can_add_remove_and_audits_both(self):
        release = self._release()
        task = self._issue()
        release.with_user(self.manager).action_release()
        Wizard = self.env["agile_community.release_correction_wizard"].with_user(self.manager)
        add = Wizard.create({
            "release_id": release.id,
            "correction_type": "issue",
            "membership_action": "add",
            "issue_id": task.id,
            "reason": "The shipped fix was omitted from the original list.",
        })
        add.action_apply()
        self.assertEqual(task.version_id, release)
        remove = Wizard.create({
            "release_id": release.id,
            "correction_type": "issue",
            "membership_action": "remove",
            "issue_id": task.id,
            "reason": "The issue was not included in this deployment.",
        })
        remove.action_apply()
        self.assertFalse(task.version_id)
        self.assertEqual(len(release.audit_ids.filtered(lambda row: row.issue_id == task)), 2)

    def test_direct_release_status_and_history_mutations_are_rejected(self):
        release = self._release()
        with self.assertRaisesRegex(ValidationError, "actor and time"):
            self.env["project.version"].with_user(self.manager).create({
                "name": "Forged release",
                "project_id": self.project.id,
                "released_by_id": self.manager.id,
                "released_at": "2026-09-25 12:00:00",
            })
        with self.assertRaisesRegex(UserError, "release action"):
            release.with_user(self.manager).write({"state": "released"})
        audit = release.audit_ids[:1]
        with self.assertRaises(AccessError):
            audit.write({"reason": "tampered"})
        with self.assertRaises(AccessError):
            audit.unlink()

    def test_release_notes_group_finished_issues_by_type(self):
        release = self._release("2.0", description="Spring drop")
        bug_type = self.env.ref("agile_community.agile_task_type_bug")
        story = self._issue("Faster search")
        story.agile_task_type_id = self.env.ref("agile_community.agile_task_type_story")
        bug = self._issue("Fix login loop")
        bug.agile_task_type_id = bug_type
        open_issue = self._issue("Still in progress")
        for task in (story, bug, open_issue):
            task.version_id = release
        self._complete(story)
        self._complete(bug)
        notes = release._release_notes_markdown()
        self.assertIn("## 2.0", notes)
        self.assertIn("Spring drop", notes)
        self.assertIn(f"### Bug (1)\n- {bug.issue_key}: Fix login loop", notes)
        self.assertIn(f"- {story.issue_key}: Faster search", notes)
        self.assertNotIn("Still in progress", notes)
        self.assertIn("1 open issue(s) are not included", notes)
        self.assertLess(notes.index("### Story"), notes.index("### Bug"))

    def test_release_notes_for_release_without_finished_issues(self):
        release = self._release("3.0")
        self.assertIn("No finished issues", release._release_notes_markdown())

    def test_release_notes_wizard_is_available_to_project_users_only_for_agile(self):
        release = self._release("4.0")
        action = release.with_user(self.contributor).action_open_release_notes()
        wizard = self.env["agile_community.release_notes_wizard"].with_user(
            self.contributor
        ).create({"release_id": release.id})
        self.assertEqual(action["res_model"], wizard._name)
        self.assertIn("## 4.0", wizard.notes)
        native = self.env["project.project"].create({"name": "Native notes"})
        plain = self.env["project.version"].create({"name": "1.0", "project_id": native.id})
        with self.assertRaises(UserError):
            plain.action_open_release_notes()

    def test_a_reviewer_can_finish_an_issue_that_blocks_another(self):
        blocker, blocked = self._issue("Blocker"), self._issue("Blocked")
        blocked.with_user(self.manager).write({"depend_on_ids": [Command.link(blocker.id)]})
        self._complete(blocker)
        self.assertEqual(blocker.agile_status, "done")
        # Adding a link is still limited to managers and contributors.
        third = self._issue("Third")
        with self.assertRaises(AccessError):
            third.with_user(self.reviewer).write({"depend_on_ids": [Command.link(blocked.id)]})
