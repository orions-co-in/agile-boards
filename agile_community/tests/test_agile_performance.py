from odoo import Command
from odoo.tests.common import TransactionCase, new_test_user

SPEC = {
    "issue_key": {}, "name": {}, "stage_id": {"fields": {"display_name": {}}}, "story_points": {},
    "user_ids": {"fields": {"display_name": {}}}, "agile_task_type_id": {"fields": {"display_name": {}}},
}


class TestAgileQueryCounts(TransactionCase):
    """H-601: the number of SQL queries behind each screen must not grow with the number of issues."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, login="perf_qc_manager", groups="project.group_project_manager")
        cls.project = cls.env["project.project"].create({
            "name": "Query count project", "privacy_visibility": "employees", "user_id": cls.manager.id,
            "agile_enabled": True, "agile_key": "QCNT", "agile_method": "scrum",
        })
        cls.sprint = cls.env["project.sprint"].with_user(cls.manager).create({
            "name": "QC sprint", "project_id": cls.project.id,
        })
        cls.epic = cls.env["project.task"].create({
            "name": "QC epic", "project_id": cls.project.id,
            "agile_task_type_id": cls.env.ref("agile_community.agile_task_type_epic").id,
        })
        cls.created = 0

    def _grow(self, count):
        self.env["project.task"].create([{
            "name": f"QC issue {self.created + i}", "project_id": self.project.id, "description": "Details",
            "parent_id": self.epic.id, "sprint_id": self.sprint.id if i % 2 else False,
            "user_ids": [Command.set(self.manager.ids)], "story_points": 3,
        } for i in range(count)])
        type(self).created += count

    def _queries(self, call):
        self.env.invalidate_all()
        before = self.env.cr.sql_log_count
        call()
        return self.env.cr.sql_log_count - before

    def _calls(self):
        user = self.env(user=self.manager)
        project = self.project.with_env(user)
        task = user["project.task"].with_context(
            default_project_id=project.id, agile_project_view=True, agile_backlog=True
        )
        domain = project._agile_backlog_domain()
        return {
            "backlog header": lambda: project.with_context(agile_backlog=True).agile_backlog_sprints(),
            "backlog sections": lambda: task.web_read_group(domain, ["sprint_id"], ["__count", "story_points:sum"], limit=80),
            "backlog rows": lambda: task.web_search_read(domain, SPEC, limit=80, order="sequence, id"),
            "epic panel": lambda: project.agile_backlog_epics(),
            "board cards": lambda: task.web_search_read(
                [("project_id", "=", project.id), ("sprint_id", "=", self.sprint.id)], SPEC, limit=40),
            "board columns": lambda: task.web_read_group(
                [("project_id", "=", project.id), ("sprint_id", "=", self.sprint.id)], ["stage_id"], ["__count"], limit=40),
            "overview": lambda: project.agile_pulse_data(),
            "roadmap": lambda: user["agile.roadmap"].roadmap_data([project.id]),
            "flow report": lambda: user["agile.report"].cfd(project.id),
            "epic burndown": lambda: user["agile.report"].burndown(project.id, "epic", self.epic.id),
        }

    def test_queries_do_not_grow_with_the_number_of_issues(self):
        self._grow(12)
        small = {name: self._queries(call) for name, call in self._calls().items()}
        self._grow(60)
        large = {name: self._queries(call) for name, call in self._calls().items()}
        for name, count in small.items():
            self.assertLessEqual(
                large[name], count + 2, f"{name}: {count} queries with 12 issues but {large[name]} with 72"
            )
