from datetime import date, timedelta

from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user


class TestAgileViewPreference(TransactionCase):
    def setUp(self):
        super().setUp()
        self.project = self.env["project.project"].create({
            "name": "Preference project",
            "agile_enabled": True,
            "agile_key": "PREF",
        })

    def test_preference_is_user_scoped_and_applies_to_board_action(self):
        preference = self.env["agile.project.view.preference"].create({
            "project_id": self.project.id,
            "density": "compact",
            "swimlane": "epic",
            "show_fix_version": True,
        })
        self.assertEqual(preference.user_id, self.env.user)
        issue = self.env["project.task"].create({
            "name": "Preference issue",
            "project_id": self.project.id,
        })
        self.assertEqual(issue.agile_card_density, "compact")
        self.assertTrue(issue.agile_card_show_fix_version)
        action = self.project.action_view_tasks()
        self.assertEqual(action["context"].get("agile_swimlane"), "epic")
        self.assertNotIn("search_default_agile_group_by_epic", action["context"])

    def test_other_user_cannot_read_or_change_my_preferences(self):
        preference = self.env["agile.project.view.preference"].create({
            "project_id": self.project.id,
        })
        outsider = new_test_user(self.env, login="agile_pref_outsider")
        with self.assertRaises(AccessError):
            preference.with_user(outsider).read(["density"])
        with self.assertRaises(AccessError):
            preference.with_user(outsider).write({"density": "compact"})

    def test_stale_member_cannot_create_or_change_preferences_without_project_read(self):
        contributor = new_test_user(
            self.env,
            login="agile_pref_stale_member",
            groups="project.group_project_user",
        )
        self.project.write({"privacy_visibility": "employees"})
        self.env["agile.project.member"].create({
            "project_id": self.project.id,
            "user_id": contributor.id,
            "role": "contributor",
        })
        preference = self.env["agile.project.view.preference"].with_user(
            contributor
        ).create({"project_id": self.project.id})
        self.project.write({"privacy_visibility": "followers"})

        self.assertFalse(self.project.with_user(contributor).has_access("read"))
        with self.assertRaises(AccessError):
            self.env["agile.project.view.preference"].with_user(contributor).create({
                "project_id": self.project.id,
            })
        with self.assertRaises(AccessError):
            preference.with_user(contributor).write({"density": "compact"})
        with self.assertRaises(AccessError):
            preference.with_user(contributor).unlink()

    def test_issue_key_and_status_preference_controls_are_not_configurable(self):
        preference = self.env["agile.project.view.preference"].create({
            "project_id": self.project.id,
        })
        self.assertNotIn("show_issue_key", preference._fields)
        self.assertNotIn("show_status", preference._fields)

    def test_shared_priority_filter_opens_only_project_issues(self):
        quick_filter = self.env["agile.project.quick.filter"].create({
            "name": "Urgent work",
            "project_id": self.project.id,
            "filter_type": "priority",
            "priority": "3",
        })
        action = quick_filter.action_open_issues()
        self.assertIn(("project_id", "=", self.project.id), action["domain"])
        self.assertIn(("agile_issue", "=", True), action["domain"])
        self.assertIn(("priority", "=", "3"), action["domain"])

    def test_shared_filter_rejects_archived_component_and_issue_type(self):
        component = self.env["agile.project.component"].create({
            "name": "Archived component filter value",
            "project_id": self.project.id,
        })
        component.active = False
        with self.assertRaisesRegex(ValidationError, "active"):
            self.env["agile.project.quick.filter"].create({
                "name": "Archived component",
                "project_id": self.project.id,
                "filter_type": "component",
                "component_id": component.id,
            })

        issue_type = self.env["agile_community.task_type"].create({
            "name": "Archived type filter value",
            "project_ids": [(6, 0, [self.project.id])],
        })
        issue_type.active = False
        with self.assertRaisesRegex(ValidationError, "active"):
            self.env["agile.project.quick.filter"].create({
                "name": "Archived issue type",
                "project_id": self.project.id,
                "filter_type": "issue_type",
                "issue_type_id": issue_type.id,
            })

    def test_shared_filter_cannot_open_when_project_is_not_agile(self):
        quick_filter = self.env["agile.project.quick.filter"].create({
            "name": "Urgent work before disable",
            "project_id": self.project.id,
            "filter_type": "priority",
            "priority": "3",
        })
        self.project.agile_enabled = False

        with self.assertRaises(AccessError):
            quick_filter.action_open_issues()

    def test_context_default_project_does_not_skip_shared_filter_manager_check(self):
        contributor = new_test_user(
            self.env,
            login="agile_filter_context_contributor",
            groups="project.group_project_user",
        )
        self.env["agile.project.member"].create({
            "project_id": self.project.id,
            "user_id": contributor.id,
            "role": "contributor",
        })
        shared_filter = self.env["agile.project.quick.filter"].create({
            "name": "Manager-owned filter",
            "project_id": self.project.id,
            "filter_type": "priority",
            "priority": "3",
        })
        with self.assertRaises(AccessError):
            shared_filter.with_user(contributor).unlink()
        self.assertTrue(shared_filter.exists())

        with self.assertRaises(AccessError):
            self.env["agile.project.quick.filter"].with_user(
                contributor
            ).with_context(default_project_id=self.project.id).create({
                "name": "Unauthorized context filter",
                "filter_type": "priority",
                "priority": "3",
            })

    def test_system_administrator_needs_native_project_access_for_shared_filters(self):
        system_user = new_test_user(
            self.env,
            login="filter_system_without_project_access",
            groups="base.group_system,project.group_project_user",
        )
        quick_filter = self.env["agile.project.quick.filter"].create({
            "name": "Private shared filter",
            "project_id": self.project.id,
            "filter_type": "priority",
            "priority": "3",
        })
        self.project.write({"privacy_visibility": "followers"})

        self.assertFalse(self.project.with_user(system_user).has_access("read"))
        self.assertFalse(
            quick_filter.with_user(system_user).has_access("read")
        )
        with self.assertRaises(AccessError):
            self.env["agile.project.quick.filter"].with_user(
                system_user
            ).create({
                "name": "Unauthorized shared filter",
                "project_id": self.project.id,
                "filter_type": "priority",
                "priority": "3",
            })


class TestAgileCardDefaults(TransactionCase):
    """R-1102: the project sets how cards start; a person's own choice still wins."""

    def setUp(self):
        super().setUp()
        self.manager = new_test_user(self.env, login="agile_card_manager", groups="project.group_project_manager")
        self.project = self.env["project.project"].with_user(self.manager).create({
            "name": "Cards", "agile_enabled": True, "agile_key": "CRD", "privacy_visibility": "employees",
        })
        self.issue = self.env["project.task"].with_user(self.manager).create({
            "name": "A card", "project_id": self.project.id,
        })
        self.Preference = self.env["agile.project.view.preference"].with_user(self.manager)

    def _issue(self):
        return self.issue.with_user(self.manager)

    def test_cards_start_from_the_project_defaults(self):
        self.assertTrue(self._issue().agile_card_show_points)
        self.assertFalse(self._issue().agile_card_show_tags)
        self.project.with_user(self.manager).write({
            "agile_card_default_points": False, "agile_card_default_tags": True, "agile_card_default_density": "compact",
        })
        issue = self._issue()
        self.assertFalse(issue.agile_card_show_points)
        self.assertTrue(issue.agile_card_show_tags)
        self.assertEqual(issue.agile_card_density, "compact")

    def test_a_preference_made_for_swimlanes_does_not_hide_the_project_defaults(self):
        self.project.with_user(self.manager).write({"agile_card_default_tags": True})
        self.project.with_user(self.manager).agile_save_board_options(swimlane="epic")
        self.assertTrue(self._issue().agile_card_show_tags)

    def test_a_personal_choice_wins_over_the_project(self):
        self.project.with_user(self.manager).write({"agile_card_default_tags": True})
        self.Preference.create({"project_id": self.project.id, "show_tags": False})
        self.assertFalse(self._issue().agile_card_show_tags)
        # The project can change later; this person keeps what they picked.
        self.project.with_user(self.manager).write({"agile_card_default_points": False})
        self.assertTrue(self._issue().agile_card_show_points)

    def test_only_an_agile_manager_changes_the_defaults(self):
        member = new_test_user(self.env, login="agile_card_member", groups="project.group_project_user")
        self.env["agile.project.member"].create({"project_id": self.project.id, "user_id": member.id, "role": "contributor"})
        with self.assertRaises(AccessError):
            self.project.with_user(member).write({"agile_card_default_tags": True})
        with self.assertRaises(AccessError):
            self.project.with_user(member).write({"agile_card_color_by": "priority"})

    def test_colour_by_priority_label_and_due_date(self):
        project = self.project.with_user(self.manager)
        issue = self._issue()
        self.assertEqual((issue.agile_card_color, issue.agile_card_color_text), ("", ""))
        project.write({"agile_card_color_by": "priority"})
        issue.write({"priority": "3"})
        self.assertEqual(self._issue().agile_card_color, "urgent")
        self.assertEqual(self._issue().agile_card_color_text, "Urgent")
        issue.write({"priority": "2"})
        self.assertEqual(self._issue().agile_card_color, "high")
        issue.write({"priority": "1"})
        self.assertEqual(self._issue().agile_card_color, "")

        project.write({"agile_card_color_by": "label"})
        tag = self.env["project.tags"].create({"name": "Alpha", "color": 4})
        issue.write({"tag_ids": [(6, 0, tag.ids)]})
        self.assertEqual(self._issue().agile_card_color, "tag-4")
        self.assertEqual(self._issue().agile_card_color_text, "Label: Alpha")

        project.write({"agile_card_color_by": "due"})
        issue.write({"date_deadline": fields.Datetime.now() - timedelta(days=2)})
        self.assertEqual(self._issue().agile_card_color, "overdue")
        issue.write({"date_deadline": fields.Datetime.now() + timedelta(days=2)})
        self.assertEqual(self._issue().agile_card_color, "soon")
        issue.write({"date_deadline": fields.Datetime.now() + timedelta(days=20)})
        self.assertEqual(self._issue().agile_card_color, "")

    def test_finished_work_is_not_coloured_overdue(self):
        self.project.with_user(self.manager).write({"agile_card_color_by": "due"})
        issue = self._issue()
        issue.write({"date_deadline": fields.Datetime.now() - timedelta(days=5)})
        self.assertEqual(self._issue().agile_card_color, "overdue")
        self.env.cr.execute("UPDATE project_task SET state = '1_done' WHERE id = %s", (issue.id,))
        issue.invalidate_recordset()
        self.assertEqual(self._issue().agile_card_color, "")


class TestAgileWorkingDays(TransactionCase):
    """R-1103: days in status and due soon count working days."""

    def setUp(self):
        super().setUp()
        self.project = self.env["project.project"].create({
            "name": "Days", "agile_enabled": True, "agile_key": "DAY",
        })

    def test_counts_only_working_days(self):
        friday, monday, saturday = date(2026, 10, 30), date(2026, 11, 2), date(2026, 10, 31)
        self.assertEqual(self.project._agile_working_days_between(friday, monday), 1)
        self.assertEqual(self.project._agile_working_days_between(friday, saturday), 0)
        self.assertEqual(self.project._agile_working_days_between(monday, friday), 0)  # not later
        self.project.write({"agile_workday_sat": True, "agile_workday_sun": True})
        self.assertEqual(self.project._agile_working_days_between(friday, monday), 3)
        self.assertEqual(self.project._agile_working_days_between(date(2026, 11, 2), date(2026, 11, 9)), 7)

    def test_a_project_needs_a_working_day(self):
        with self.assertRaises(ValidationError):
            self.project.write({
                "agile_workday_mon": False, "agile_workday_tue": False, "agile_workday_wed": False,
                "agile_workday_thu": False, "agile_workday_fri": False,
            })

    def test_days_in_status_ages_open_work_only(self):
        self.project.write({"agile_workday_sat": True, "agile_workday_sun": True})  # every day counts
        issue = self.env["project.task"].create({"name": "Aging", "project_id": self.project.id})
        self.env.cr.execute(
            "UPDATE project_task SET date_last_stage_update = now() - interval '4 days' WHERE id = %s", (issue.id,)
        )
        issue.invalidate_recordset()
        self.assertEqual(issue.agile_days_in_status, 4)
        self.project.write({"agile_workday_sat": False, "agile_workday_sun": False})
        issue.invalidate_recordset()
        self.assertLessEqual(issue.agile_days_in_status, 4)
        self.env.cr.execute("UPDATE project_task SET state = '1_done' WHERE id = %s", (issue.id,))
        issue.invalidate_recordset()
        self.assertEqual(issue.agile_days_in_status, 0)

    def test_the_days_line_can_be_turned_off_for_the_team(self):
        issue = self.env["project.task"].create({"name": "Line", "project_id": self.project.id})
        self.assertTrue(issue.agile_card_show_days)
        self.project.write({"agile_card_default_days": False})
        self.assertFalse(issue.agile_card_show_days)

    def test_due_soon_colour_counts_working_days(self):
        self.project.write({"agile_card_color_by": "due"})
        issue = self.env["project.task"].create({"name": "Due", "project_id": self.project.id})
        far = fields.Datetime.now() + timedelta(days=5)
        issue.write({"date_deadline": far})
        # Five calendar days away is four or five working days, never "soon" under a Monday to Friday week
        # unless the weekend falls inside the window; with every day counted it is five, so not soon.
        self.project.write({"agile_workday_sat": True, "agile_workday_sun": True})
        issue.invalidate_recordset()
        self.assertEqual(issue.agile_card_color, "")
        issue.write({"date_deadline": fields.Datetime.now() + timedelta(days=2)})
        self.assertEqual(issue.agile_card_color, "soon")
