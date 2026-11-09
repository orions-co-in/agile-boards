from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user


class TestAgileRoadmapShare(TransactionCase):
    """U-1163: a roadmap view shared with named people, read only, through each viewer's own access."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.owner = new_test_user(cls.env, login="rs_owner", groups="project.group_project_manager")
        cls.viewer = new_test_user(cls.env, login="rs_viewer", groups="project.group_project_user")
        cls.stranger = new_test_user(cls.env, login="rs_stranger", groups="project.group_project_user")
        cls.project = cls._project("RSA", members=(cls.viewer,))
        cls.private = cls._project("RSB", members=())
        cls.today = fields.Date.context_today(cls.project)
        cls.epic_type = cls.env.ref("agile_community.agile_task_type_epic")
        cls.release = cls.env["project.version"].sudo().create({"name": "R1", "project_id": cls.project.id})
        cls.epic = cls.env["project.task"].with_user(cls.owner).create({
            "name": "Epic", "project_id": cls.project.id, "agile_task_type_id": cls.epic_type.id,
            "agile_planned_start": cls.today, "agile_planned_end": cls.today + timedelta(days=9),
            "version_id": cls.release.id,
        })
        cls.Share = cls.env["agile.roadmap.share"]

    @classmethod
    def _project(cls, key, members):
        project = cls.env["project.project"].with_user(cls.owner).create({
            "name": f"Share {key}", "privacy_visibility": "employees", "agile_enabled": True,
            "agile_key": key, "agile_method": "scrum",
        })
        Member = cls.env["agile.project.member"].sudo()
        Member.search([("project_id", "=", project.id), ("user_id", "!=", cls.owner.id)]).unlink()
        for user in members:
            Member.create({"project_id": project.id, "user_id": user.id, "role": "contributor"})
        return project

    def _share(self, projects=None, people=None, **kwargs):
        return self.Share.with_user(self.owner).share_create(
            kwargs.pop("name", "Quarter plan"), [p.id for p in (projects or self.project)],
            [u.id for u in (people or self.viewer)], **kwargs)

    def test_named_people_see_it_and_others_do_not(self):
        share = self._share()
        listed = self.Share.with_user(self.viewer).share_list()
        self.assertEqual([s["id"] for s in listed["shared"]], [share["id"]])
        self.assertFalse(listed["mine"])
        self.assertFalse(self.Share.with_user(self.stranger).share_list()["shared"])
        with self.assertRaises(AccessError):
            self.Share.with_user(self.stranger).share_data(share["id"])

    def test_a_viewer_cannot_change_or_delete_it(self):
        share = self._share()
        for call in (
            lambda: self.Share.with_user(self.viewer).share_update(share["id"], [self.viewer.id]),
            lambda: self.Share.with_user(self.viewer).share_delete(share["id"]),
            lambda: self.Share.with_user(self.viewer).browse(share["id"]).write({"name": "Mine now"}),
        ):
            with self.assertRaises(AccessError):
                call()
        self.assertTrue(self.Share.browse(share["id"]).exists())

    def test_a_viewer_gets_the_saved_options_and_the_roadmap(self):
        share = self._share(hide_done=True, colour_by="release")
        result = self.Share.with_user(self.viewer).share_data(share["id"])
        self.assertEqual((result["share"]["colour_by"], result["share"]["hide_done"], result["share"]["mine"]), ("release", True, False))
        row = result["data"]["projects"][0]["rows"][0]
        self.assertEqual((row["name"], row["release"], row["release_id"]), ("Epic", "R1", self.release.id))
        self.assertNotIn("user_ids", result["share"])

    def test_projects_the_viewer_cannot_open_are_left_out_and_counted(self):
        self.env["project.task"].with_user(self.owner).create({
            "name": "Secret epic", "project_id": self.private.id, "agile_task_type_id": self.epic_type.id,
            "agile_planned_start": self.today, "agile_planned_end": self.today + timedelta(days=3),
        })
        share = self._share(projects=self.project | self.private)
        result = self.Share.with_user(self.viewer).share_data(share["id"])
        names = [p["name"] for p in result["data"]["projects"]]
        self.assertEqual(names, [self.project.name])
        self.assertEqual(result["hidden_projects"], 1)
        only_private = self._share(projects=self.private, people=self.viewer, name="Hidden")
        with self.assertRaises(UserError):
            self.Share.with_user(self.viewer).share_data(only_private["id"])

    def test_only_people_from_the_owners_projects_can_be_named(self):
        with self.assertRaises(UserError):
            self._share(people=self.stranger)
        with self.assertRaises(UserError):
            self._share(people=self.viewer, name="  ")

    def test_only_projects_the_owner_belongs_to_can_be_shared(self):
        other_manager = new_test_user(self.env, login="rs_other", groups="project.group_project_manager")
        foreign = self.env["project.project"].with_user(other_manager).create({
            "name": "Foreign", "privacy_visibility": "followers", "agile_enabled": True, "agile_key": "RSF",
            "agile_method": "scrum",
        })
        with self.assertRaises(UserError):
            self._share(projects=foreign)

    def test_the_owner_changes_who_sees_it_and_deletes_it(self):
        share = self._share()
        self.assertEqual(self.Share.with_user(self.owner).share_update(share["id"], [self.viewer.id])["people"], self.viewer.name)
        self.Share.with_user(self.owner).share_delete(share["id"])
        self.assertFalse(self.Share.with_user(self.viewer).share_list()["shared"])

    def test_an_owner_has_at_most_thirty_shared_roadmaps(self):
        for index in range(30):
            self._share(name=f"View {index}")
        with self.assertRaises(UserError):
            self._share(name="One too many")

    def test_a_shared_roadmap_needs_people_and_projects(self):
        with self.assertRaises(ValidationError):
            self.Share.sudo().create({"name": "Empty", "owner_id": self.owner.id})
