from odoo.tests.common import TransactionCase
from odoo.tools import file_open


class TestAgileDemoSeed(TransactionCase):
    """H-603: the demo project loader in docs/demo keeps working against the real workflow."""

    def _run_seed(self):
        with file_open("agile_community/demo/agile_demo_seed.py") as handle:
            source = handle.read()
        exec(compile(source, "agile_demo_seed.py", "exec"), {"env": self.env(context=dict(self.env.context, agile_demo_no_commit=True))})  # noqa: S102

    def test_the_demo_project_loads_with_every_kind_of_data(self):
        self._run_seed()
        project = self.env["project.project"].search([("agile_key", "=", "SHOP")])
        self.assertEqual(len(project), 1)
        tasks = self.env["project.task"].search([("project_id", "=", project.id)])
        self.assertEqual(len(tasks), 28)
        self.assertEqual(len(tasks.filtered("agile_is_epic")), 3)
        statuses = set(tasks.mapped("agile_status"))
        self.assertTrue({"backlog", "ready", "progress", "review", "done"} <= statuses)
        sprints = project.sprint_ids
        self.assertEqual(sorted(sprints.mapped("state")), ["done", "draft", "in_progress"])
        releases = self.env["project.version"].search([("project_id", "=", project.id)])
        self.assertEqual(sorted(releases.mapped("state")), ["planned", "released"])
        self.assertEqual(len(tasks.filtered("agile_blocked")), 1)
        if "agile.git.event" in self.env:
            self.assertEqual(self.env["agile.git.event"].search_count([("project_id", "=", project.id)]), 2)
        roles = {m.user_id.login: m.role for m in project.agile_member_ids}
        self.assertEqual(roles.get("demo_manager"), "manager", roles)
        self.assertEqual(roles["demo_dev"], "contributor")
        self.assertEqual(roles["demo_reviewer"], "reviewer")

    def test_loading_twice_does_not_duplicate(self):
        self._run_seed()
        self._run_seed()
        self.assertEqual(self.env["project.project"].search_count([("agile_key", "=", "SHOP")]), 1)
