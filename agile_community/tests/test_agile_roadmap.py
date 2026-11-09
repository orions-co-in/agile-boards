from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user


class TestAgileRoadmap(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(
            cls.env,
            login="roadmap_manager",
            groups="project.group_project_manager",
        )
        cls.contributor = new_test_user(
            cls.env,
            login="roadmap_contributor",
            groups="project.group_project_user",
        )
        cls.project = cls.env["project.project"].create({
            "name": "Roadmap project",
            "privacy_visibility": "employees",
            "user_id": cls.manager.id,
        })
        cls.native_task = cls.env["project.task"].create({
            "name": "Native task retained by Agile setup",
            "project_id": cls.project.id,
        })
        cls.project.write({"agile_enabled": True, "agile_key": "ROAD"})

    def _issue(self, name, **values):
        return self.env["project.task"].with_user(self.manager).create({
            "name": name,
            "project_id": self.project.id,
            "description": "Roadmap test issue.",
            **values,
        })

    def test_projection_combines_explicit_issue_sprint_and_release_dates(self):
        dated_issue = self._issue(
            "Scheduled issue",
            agile_planned_start="2026-10-01",
            agile_planned_end="2026-10-04",
        )
        epic = self._issue(
            "Scheduled Epic",
            agile_task_type_id=self.env.ref(
                "agile_community.agile_task_type_epic"
            ).id,
            agile_planned_start="2026-10-02",
            agile_planned_end="2026-10-12",
        )
        self._issue(
            "Scheduled Epic child",
            parent_id=epic.id,
            agile_planned_start="2026-10-03",
            agile_planned_end="2026-10-05",
        )
        unscheduled_issue = self._issue("Unscheduled issue")
        sprint = self.env["project.sprint"].with_user(self.manager).create({
            "name": "Roadmap sprint",
            "project_id": self.project.id,
            "date_start": "2026-10-05",
            "date_end": "2026-10-11",
        })
        release = self.env["project.version"].with_user(self.manager).create({
            "name": "Roadmap release",
            "project_id": self.project.id,
            "release_date": "2026-10-15",
        })

        items = self.env["agile.roadmap.item"].with_user(self.manager).search([
            ("project_id", "=", self.project.id),
        ])

        self.assertEqual(set(items.mapped("item_type")), {"issue", "sprint", "release"})
        self.assertIn(dated_issue.id, items.mapped("issue_id").ids)
        epic_item = items.filtered(lambda item: item.issue_id == epic)
        self.assertEqual(epic_item.child_issue_count, 1)
        self.assertNotIn(unscheduled_issue.id, items.mapped("issue_id").ids)
        self.assertNotIn(self.native_task.id, items.mapped("issue_id").ids)
        self.assertIn(sprint.id, items.mapped("sprint_id").ids)
        self.assertIn(release.id, items.mapped("release_id").ids)

        issue_item = items.filtered(lambda item: item.issue_id == dated_issue)
        action = issue_item.action_open_source()
        self.assertEqual(action["res_model"], "project.task")
        self.assertEqual(action["res_id"], dated_issue.id)

    def test_date_editing_is_project_manager_only_and_range_checked(self):
        issue = self._issue("Dated issue")

        with self.assertRaises(AccessError):
            issue.with_user(self.contributor).write({
                "agile_planned_start": "2026-10-09",
            })
        with self.assertRaises(ValidationError):
            issue.with_user(self.manager).write({
                "agile_planned_start": "2026-10-10",
                "agile_planned_end": "2026-10-09",
            })

    def test_source_action_denies_unassigned_project_manager(self):
        outsider = new_test_user(
            self.env,
            login="roadmap_unassigned_project_manager",
            groups="project.group_project_manager",
        )
        issue = self._issue(
            "Agile issue denied outside the team",
            agile_planned_start="2026-10-01",
            agile_planned_end="2026-10-02",
        )
        self.assertFalse(issue.with_user(outsider).has_access("read"))

        roadmap = self.env["agile.roadmap.item"].with_user(self.manager).search([
            ("issue_id", "=", issue.id),
        ], limit=1)
        self.assertFalse(
            self.env["agile.roadmap.item"].with_user(outsider).search([
                ("id", "=", roadmap.id),
            ])
        )
        with self.assertRaises(AccessError):
            roadmap.with_user(outsider).action_open_source()


class TestAgileRoadmapDerivedDates(TestAgileRoadmap):
    """U-1461: an epic with no dates takes its bar from its children."""

    def _item(self, issue):
        self.env.flush_all()
        self.env.invalidate_all()
        return self.env["agile.roadmap.item"].sudo().search([("issue_id", "=", issue.id)])

    def test_epic_bar_comes_from_children_and_typed_dates_override(self):
        epic = self._issue("Derived epic", agile_task_type_id=self.env.ref("agile_community.agile_task_type_epic").id)
        self.assertFalse(self._item(epic))
        self._issue("Child one", parent_id=epic.id, agile_planned_start="2026-10-03", agile_planned_end="2026-10-05")
        self._issue("Child two", parent_id=epic.id, agile_planned_start="2026-10-10", agile_planned_end="2026-10-20")
        item = self._item(epic)
        self.assertTrue(item.is_derived)
        self.assertEqual((str(item.date_start), str(item.date_end)), ("2026-10-03", "2026-10-20"))
        epic.with_user(self.manager).write({"agile_planned_start": "2026-09-01", "agile_planned_end": "2026-09-30"})
        item = self._item(epic)
        self.assertFalse(item.is_derived)
        self.assertEqual((str(item.date_start), str(item.date_end)), ("2026-09-01", "2026-09-30"))
