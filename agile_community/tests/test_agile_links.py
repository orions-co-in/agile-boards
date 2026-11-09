from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user


class TestAgileLinks(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        group = "project.group_project_user"
        cls.manager = new_test_user(cls.env, login="lk_manager", groups="project.group_project_manager", name="Mia Manager")
        cls.contributor = new_test_user(cls.env, login="lk_contrib", groups=group, name="Cora Contributor")
        cls.stakeholder = new_test_user(cls.env, login="lk_stake", groups=group, name="Sam Stakeholder")
        cls.outsider = new_test_user(cls.env, login="lk_outsider", groups=group, name="Otto Outsider")
        Project = cls.env["project.project"].with_user(cls.manager)
        cls.project = Project.create({
            "name": "Links project", "privacy_visibility": "employees", "agile_enabled": True,
            "agile_key": "LNK", "agile_method": "scrum", "allow_task_dependencies": True})
        cls.other_project = Project.create({
            "name": "Other project", "privacy_visibility": "followers", "agile_enabled": True,
            "agile_key": "OTH", "agile_method": "scrum", "allow_task_dependencies": True})
        Member = cls.env["agile.project.member"].sudo()
        for user, role in ((cls.contributor, "contributor"), (cls.stakeholder, "stakeholder")):
            member = Member.search([("project_id", "=", cls.project.id), ("user_id", "=", user.id)])
            if member:
                member.role = role
            else:
                Member.create({"project_id": cls.project.id, "user_id": user.id, "role": role})
        Member.search([("project_id", "=", cls.project.id), ("user_id", "=", cls.outsider.id)]).unlink()

    def _issue(self, name="Issue", project=None):
        return self.env["project.task"].with_user(self.manager).create({
            "name": name, "project_id": (project or self.project).id, "description": "x"})

    def _kinds(self, issue, user=None):
        data = issue.with_user(user or self.manager).agile_links_data()
        return {group["kind"]: [item["id"] for item in group["items"]] for group in data["groups"]}

    def test_each_type_shows_on_both_issues_with_its_own_wording(self):
        a, b = self._issue("A"), self._issue("B")
        pairs = {
            "blocks": ("blocks", "blocked_by"),
            "clones": ("clones", "cloned_by"),
            "duplicates": ("duplicates", "duplicated_by"),
            "relates": ("relates", "relates"),
        }
        for kind, (mine, theirs) in pairs.items():
            a.with_user(self.manager).agile_add_link(kind, b.id)
            self.assertEqual(self._kinds(a)[mine], [b.id], kind)
            self.assertEqual(self._kinds(b)[theirs], [a.id], kind)

    def test_the_other_direction_is_stored_from_the_other_side(self):
        a, b = self._issue("A"), self._issue("B")
        b.with_user(self.manager).agile_add_link("cloned_by", a.id)
        self.assertEqual(self._kinds(a)["clones"], [b.id])
        self.assertEqual(self._kinds(b)["cloned_by"], [a.id])

    def test_blocks_stays_in_step_with_the_dependency_field(self):
        a, b = self._issue("A"), self._issue("B")
        a.with_user(self.manager).agile_add_link("blocks", b.id)
        self.assertEqual(b.depend_on_ids, a)
        b.with_user(self.manager).agile_remove_link("blocked_by", a.id)
        self.assertFalse(b.depend_on_ids)
        b.with_user(self.manager).write({"depend_on_ids": [Command.link(a.id)]})
        self.assertEqual(self._kinds(a)["blocks"], [b.id])

    def test_legacy_duplicate_rows_keep_neutral_wording(self):
        a, b = self._issue("A"), self._issue("B")
        a.with_user(self.manager).write({"agile_duplicate_issue_ids": [Command.set([b.id])]})
        self.assertEqual(self._kinds(a)["duplicates_either"], [b.id])
        self.assertEqual(self._kinds(b)["duplicates_either"], [a.id])

    def test_remove_takes_the_link_away_on_both_sides(self):
        a, b = self._issue("A"), self._issue("B")
        a.with_user(self.manager).agile_add_link("clones", b.id)
        a.with_user(self.manager).agile_remove_link("clones", b.id)
        self.assertEqual(self._kinds(a), {})
        self.assertEqual(self._kinds(b), {})

    def test_refusals(self):
        a, b = self._issue("A"), self._issue("B")
        manager = a.with_user(self.manager)
        with self.assertRaises(ValidationError):
            manager.agile_add_link("relates", a.id)
        manager.agile_add_link("relates", b.id)
        with self.assertRaises(ValidationError):
            manager.agile_add_link("relates", b.id)
        manager.agile_add_link("blocks", b.id)
        with self.assertRaises(ValidationError) as loop:
            b.with_user(self.manager).agile_add_link("blocks", a.id)
        self.assertIn("would make a loop", str(loop.exception))
        with self.assertRaises(ValidationError):
            manager.agile_add_link("nonsense", b.id)

    def test_loops_through_a_third_issue_are_refused(self):
        a, b, c = self._issue("A"), self._issue("B"), self._issue("C")
        a.with_user(self.manager).agile_add_link("blocks", b.id)
        b.with_user(self.manager).agile_add_link("blocks", c.id)
        with self.assertRaises(ValidationError):
            c.with_user(self.manager).agile_add_link("blocks", a.id)

    def test_who_may_change_links(self):
        a, b = self._issue("A"), self._issue("B")
        a.with_user(self.contributor).agile_add_link("relates", b.id)
        self.assertTrue(a.with_user(self.contributor).agile_links_data()["can_edit"])
        stakeholder = a.with_user(self.stakeholder)
        self.assertFalse(stakeholder.agile_links_data()["can_edit"])
        self.assertEqual(self._kinds(a, self.stakeholder)["relates"], [b.id])
        with self.assertRaises(AccessError):
            stakeholder.agile_add_link("clones", b.id)
        with self.assertRaises(AccessError):
            stakeholder.agile_remove_link("relates", b.id)

    def test_links_to_issues_the_user_cannot_read_are_counted_not_named(self):
        a = self._issue("A")
        secret = self._issue("Secret", self.other_project)
        a.with_user(self.manager).agile_add_link("relates", secret.id)
        data = a.with_user(self.contributor).agile_links_data()
        self.assertEqual(data["hidden"], 1)
        self.assertEqual(data["groups"], [])
        self.assertEqual(a.with_user(self.manager).agile_links_data()["hidden"], 0)

    def test_cannot_add_a_link_to_an_unreadable_issue(self):
        a = self._issue("A")
        secret = self._issue("Secret", self.other_project)
        with self.assertRaises(AccessError):
            a.with_user(self.contributor).agile_add_link("relates", secret.id)

    def test_the_source_must_be_one_of_the_two_issues(self):
        a, b, c = self._issue("A"), self._issue("B"), self._issue("C")
        Link = self.env["agile_community.issue_link"].sudo()
        with self.assertRaises(ValidationError):
            Link.create({
                "issue_a_id": min(a.id, b.id), "issue_b_id": max(a.id, b.id),
                "link_type": "clones", "source_id": c.id})

    def test_the_card_text_names_one_blocker_and_counts_the_rest(self):
        a, b, c = self._issue("A"), self._issue("B"), self._issue("C")
        a.with_user(self.manager).agile_add_link("blocked_by", b.id)
        a.invalidate_recordset()
        self.assertEqual(a.agile_blocked_by_text, b.issue_key)
        a.with_user(self.manager).agile_add_link("blocked_by", c.id)
        a.invalidate_recordset()
        self.assertEqual(a.agile_blocked_by_text, f"{min(b.issue_key, c.issue_key)} and 1 more")

    def test_blocking_links_need_the_project_setting(self):
        a, b = self._issue("A"), self._issue("B")
        self.project.allow_task_dependencies = False
        a.invalidate_recordset()
        self.assertFalse(a.with_user(self.manager).agile_links_data()["allow_blocking"])
        with self.assertRaises(ValidationError):
            a.with_user(self.manager).agile_add_link("blocks", b.id)
        a.with_user(self.manager).agile_add_link("relates", b.id)


class TestAgileClone(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        group = "project.group_project_user"
        cls.manager = new_test_user(cls.env, login="cl_manager", groups="project.group_project_manager", name="Mia Manager")
        cls.contributor = new_test_user(cls.env, login="cl_contrib", groups=group, name="Cora Contributor")
        cls.stakeholder = new_test_user(cls.env, login="cl_stake", groups=group, name="Sam Stakeholder")
        cls.project = cls.env["project.project"].with_user(cls.manager).create({
            "name": "Clone project", "privacy_visibility": "employees", "agile_enabled": True,
            "agile_key": "CLN", "agile_method": "scrum"})
        Member = cls.env["agile.project.member"].sudo()
        for user, role in ((cls.contributor, "contributor"), (cls.stakeholder, "stakeholder")):
            member = Member.search([("project_id", "=", cls.project.id), ("user_id", "=", user.id)])
            if member:
                member.role = role
            else:
                Member.create({"project_id": cls.project.id, "user_id": user.id, "role": role})
        cls.field = cls.env["agile.custom.field"].with_user(cls.manager).create({
            "name": "Customer", "project_id": cls.project.id, "field_type": "text"}) if "agile.custom.field" in cls.env else None
        cls.tag = cls.env["project.tags"].create({"name": "urgent"})
        cls.sprint = cls.env["project.sprint"].with_user(cls.manager).create({
            "name": "S1", "project_id": cls.project.id, "date_start": "2026-11-01",
            "date_option": "custom", "date_end": "2026-11-14"})
        cls.original = cls.env["project.task"].with_user(cls.manager).create({
            "name": "Checkout", "project_id": cls.project.id, "description": "<p>Pay.</p>",
            "story_points": 5, "story_points_estimated": True, "tag_ids": [Command.set(cls.tag.ids)],
            "user_ids": [Command.set([cls.contributor.id])], "sprint_id": cls.sprint.id})
        cls.child = cls.env["project.task"].with_user(cls.manager).create({
            "name": "Card form", "project_id": cls.project.id, "parent_id": cls.original.id,
            "agile_task_type_id": cls.env.ref("agile_community.agile_task_type_task").id})
        if cls.field:
            value = cls.original.sudo().agile_custom_value_ids.filtered(lambda v: v.field_id == cls.field)
            value.value_char = "ACME"
        cls.env["ir.attachment"].create({
            "name": "spec.txt", "raw": b"hello", "res_model": "project.task", "res_id": cls.original.id})

    def test_clone_copies_the_content_and_none_of_the_history(self):
        result = self.original.with_user(self.contributor).agile_clone()
        clone = self.env["project.task"].browse(result["id"])
        self.assertEqual(clone.name, "Clone of Checkout")
        self.assertEqual((clone.description, clone.story_points, clone.tag_ids), (self.original.description, 5, self.tag))
        self.assertTrue(clone.story_points_estimated)
        self.assertEqual(clone.agile_status, "backlog")
        self.assertNotEqual(clone.issue_key, self.original.issue_key)
        self.assertFalse(clone.sprint_id)
        self.assertFalse(clone.user_ids)
        if self.field:
            self.assertEqual(clone.sudo().agile_custom_value_ids.filtered(lambda v: v.field_id == self.field).value_char, "ACME")
        self.assertEqual(clone.child_ids.mapped("name"), ["Card form"])
        self.assertFalse(self.env["ir.attachment"].search([("res_model", "=", "project.task"), ("res_id", "=", clone.id)]))
        self.assertEqual(self.original.sudo().message_ids.filtered(lambda m: m.id in clone.sudo().message_ids.ids).ids, [])

    def test_clone_options_and_the_clones_link(self):
        result = self.original.with_user(self.manager).agile_clone(
            title="Checkout v2", copy_subtasks=False, copy_attachments=True, same_sprint=True)
        clone = self.env["project.task"].browse(result["id"])
        self.assertEqual(clone.name, "Checkout v2")
        self.assertFalse(clone.child_ids)
        self.assertEqual(clone.sprint_id, self.sprint)
        self.assertEqual(self.env["ir.attachment"].search_count([("res_model", "=", "project.task"), ("res_id", "=", clone.id)]), 1)
        data = clone.with_user(self.manager).agile_links_data()
        self.assertEqual([g["kind"] for g in data["groups"]], ["clones"])
        self.assertEqual(self.original.with_user(self.manager).agile_links_data()["groups"][0]["kind"], "cloned_by")

    def test_an_active_sprint_is_not_joined(self):
        self.sprint.sudo()._write({"state": "in_progress"})
        self.sprint.invalidate_recordset(["state"])
        clone = self.env["project.task"].browse(
            self.original.with_user(self.manager).agile_clone(same_sprint=True)["id"])
        self.assertFalse(clone.sprint_id)

    def test_move_to_is_offered_to_workers_not_to_stakeholders(self):
        """E2E-012: the phone card's Move to… link follows the role."""
        self.assertTrue(self.original.with_user(self.manager).can_agile_move_to)
        self.assertTrue(self.original.with_user(self.contributor).can_agile_move_to)
        self.assertFalse(self.original.with_user(self.stakeholder).can_agile_move_to)

    def test_a_stakeholder_cannot_clone(self):
        with self.assertRaises(AccessError):
            self.original.with_user(self.stakeholder).agile_clone()

    def test_the_dialog_clones_as_a_contributor_and_offers_the_sprint_only_while_planned(self):
        action = self.original.with_user(self.contributor).action_agile_open_clone()
        wizard = self.env["agile_community.clone_wizard"].with_user(self.contributor).browse(action["res_id"])
        self.assertEqual(wizard.name, "Clone of Checkout")
        self.assertFalse(wizard.sprint_can_join, "standard scheme: only managers change sprint membership")
        self.assertTrue(self.original.with_user(self.contributor).can_agile_clone)
        self.assertFalse(self.original.with_user(self.stakeholder).can_agile_clone)
        wizard.write({"name": "Checkout copy", "same_sprint": True})
        clone = self.env["project.task"].browse(wizard.action_clone()["res_id"])
        self.assertEqual((clone.name, clone.sprint_id.id), ("Checkout copy", False))
        self.project.with_user(self.manager).write({"agile_permission_scheme": "open"})
        wizard.invalidate_recordset()
        self.assertTrue(wizard.sprint_can_join)
        clone = self.env["project.task"].browse(wizard.action_clone()["res_id"])
        self.assertEqual(clone.sprint_id, self.sprint)

    def test_a_released_version_is_not_copied(self):
        release = self.env["project.version"].sudo().create({"name": "1.0", "project_id": self.project.id})
        self.original.sudo().version_id = release
        release.sudo()._write({"state": "released"})
        release.invalidate_recordset(["state"])
        clone = self.env["project.task"].browse(self.original.with_user(self.manager).agile_clone()["id"])
        self.assertFalse(clone.version_id)


class TestAgileLinkQuery(TestAgileLinks):
    """The query terms link, blocked and blocks (I-1015)."""

    def _find(self, text):
        from odoo.addons.agile_community.models.agile_query import AgileQuery

        domain, _words = AgileQuery(self.env(user=self.manager), self.project).compile(text)
        return self.env["project.task"].with_user(self.manager).search(
            [("project_id", "=", self.project.id)] + domain)

    def setUp(self):
        super().setUp()
        self.a, self.b, self.c, self.d = (self._issue(name) for name in "ABCD")
        manager = self.a.with_user(self.manager)
        manager.agile_add_link("blocks", self.b.id)
        manager.agile_add_link("clones", self.c.id)

    def test_blocked_and_blocks(self):
        self.assertEqual(self._find(f"blocked = {self.a.issue_key}"), self.b)
        self.assertEqual(self._find(f"blocks = {self.b.issue_key}"), self.a)
        self.assertEqual(self._find("blocked IS NOT EMPTY"), self.b)
        self.assertEqual(self._find("blocks IS NOT EMPTY"), self.a)

    def test_link_finds_either_end_of_any_type(self):
        self.assertEqual(self._find(f"link = {self.a.issue_key}"), self.b | self.c)
        self.assertEqual(self._find(f"link = {self.c.issue_key}"), self.a)
        self.assertEqual(self._find("link IS EMPTY"), self.d)
        self.assertEqual(self._find("link IS NOT EMPTY"), self.a | self.b | self.c)

    def test_an_unknown_key_says_so(self):
        from odoo.addons.agile_community.models.agile_query import QueryError

        with self.assertRaises(QueryError):
            self._find("link = NOPE-1")


class TestAgileFlag(TestAgileClone):
    """Flag an issue (J-1025)."""

    def _notes(self, task):
        return " ".join(task.sudo().message_ids.mapped("body"))

    def test_flagging_does_not_change_status_and_is_logged_both_ways(self):
        issue = self.original.with_user(self.contributor)
        status = issue.agile_status
        issue.write({"agile_flagged": True, "agile_flag_note": "Waiting on the vendor"})
        self.assertEqual(issue.agile_status, status)
        self.assertIn("flagged this issue", self._notes(issue))
        self.assertIn("Waiting on the vendor", self._notes(issue))
        issue.action_agile_toggle_flag()
        self.assertFalse(issue.agile_flagged)
        self.assertFalse(issue.agile_flag_note, "the note goes with the flag")
        self.assertIn("removed the flag", self._notes(issue))

    def test_editing_the_note_of_a_flagged_issue_adds_no_line(self):
        issue = self.original.with_user(self.manager)
        issue.action_agile_toggle_flag()
        lines = len(issue.sudo().message_ids)
        issue.write({"agile_flag_note": "Now with a note"})
        self.assertEqual(len(issue.sudo().message_ids), lines)

    def test_a_stakeholder_cannot_flag(self):
        with self.assertRaises(AccessError):
            self.original.with_user(self.stakeholder).action_agile_toggle_flag()

    def test_the_flag_is_filterable_and_not_copied(self):
        self.original.with_user(self.manager).action_agile_toggle_flag()
        found = self.env["project.task"].with_user(self.manager).search(
            [("project_id", "=", self.project.id), ("agile_flagged", "=", True)])
        self.assertEqual(found, self.original)
        clone = self.env["project.task"].browse(self.original.with_user(self.manager).agile_clone()["id"])
        self.assertFalse(clone.agile_flagged)
