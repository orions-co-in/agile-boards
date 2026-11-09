from odoo.tests import HttpCase, tagged
from odoo.tests.common import new_test_user


@tagged("post_install", "-at_install")
class TestAgileTours(HttpCase):
    """Browser tours for the backlog and the board.

    They need Chrome and websocket-client; where those are missing Odoo skips them,
    and the same tours can be run by hand: open the project with ?debug=tests and run
    `odoo.startTour("agile_backlog_tour", {mode: "auto"})` in the console.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(
            cls.env,
            login="tour_manager",
            groups="project.group_project_manager",
        )
        cls.project = cls.env["project.project"].with_user(cls.user).create({
            "name": "Tour Project",
            "privacy_visibility": "employees",
            "agile_enabled": True,
            "agile_key": "TUR",
            "agile_method": "scrum",
        })
        epic_type = cls.env["agile_community.task_type"].search([("is_epic", "=", True)], limit=1)
        Task = cls.env["project.task"].with_user(cls.user)
        epic = Task.create({
            "name": "Tour epic", "project_id": cls.project.id,
            "agile_task_type_id": epic_type.id, "description": "Epic",
        })
        Task.create({"name": "Epic child", "project_id": cls.project.id, "parent_id": epic.id})
        Task.create({"name": "Loose issue", "project_id": cls.project.id})
        sprint = cls.env["project.sprint"].with_user(cls.user).create({
            "name": "Tour sprint", "project_id": cls.project.id,
            "date_start": cls.env["project.sprint"].default_get(["date_start"])["date_start"],
            "date_option": "2_weeks",
        })
        for name in ("Tour issue A", "Tour issue B"):
            Task.create({
                "name": name, "project_id": cls.project.id, "sprint_id": sprint.id,
                "user_ids": [(6, 0, [cls.user.id])],
            })
        sprint.action_confirm_plan()
        sprint.action_start()

    def test_backlog_tour(self):
        self.start_tour("/odoo/action-project.open_view_project_all", "agile_backlog_tour", login="tour_manager")

    def test_board_tour(self):
        self.start_tour("/odoo/action-project.open_view_project_all", "agile_board_tour", login="tour_manager")
