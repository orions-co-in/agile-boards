from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, new_test_user


class TestAgileRoadmapPage(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, login="rm_manager", groups="project.group_project_manager")
        cls.outsider = new_test_user(cls.env, login="rm_outsider", groups="project.group_project_user")
        cls.project = cls._project("RMA")
        cls.other = cls._project("RMB")
        cls.today = fields.Date.context_today(cls.project)
        cls.Roadmap = cls.env["agile.roadmap"].with_user(cls.manager)
        cls.epic_type = cls.env.ref("agile_community.agile_task_type_epic")

    @classmethod
    def _project(cls, key):
        project = cls.env["project.project"].with_user(cls.manager).create({
            "name": f"Roadmap {key}", "privacy_visibility": "employees", "agile_enabled": True,
            "agile_key": key, "agile_method": "scrum",
        })
        cls.env["agile.project.member"].sudo().search([
            ("project_id", "=", project.id), ("user_id", "=", cls.outsider.id)]).unlink()
        return project

    def _issue(self, name, start, end, project=None, parent=None, epic=False, assigned=False):
        values = {
            "name": name, "project_id": (project or self.project).id, "description": "Roadmap issue.",
            "agile_planned_start": self.today + timedelta(days=start),
            "agile_planned_end": self.today + timedelta(days=end),
            "user_ids": [Command.set([self.manager.id])] if assigned else [Command.clear()],
        }
        if epic:
            values["agile_task_type_id"] = self.epic_type.id
        if parent:
            values["parent_id"] = parent.id
        return self.env["project.task"].with_user(self.manager).create(values)

    def _data(self, projects=None, **kwargs):
        return self.Roadmap.roadmap_data([p.id for p in (projects or self.project)], **kwargs)

    def _rows(self, data, project=0):
        return data["projects"][project]["rows"]

    def test_epic_row_carries_dates_children_and_progress(self):
        epic = self._issue("Epic", 0, 20, epic=True)
        child = self._issue("Child", 2, 6, parent=epic)
        done = self._issue("Done child", 3, 5, parent=epic, assigned=True)
        for step in ("mark_ready", "start", "send_review", "complete"):
            getattr(done.with_user(self.manager), f"action_agile_{step}")()
        rows = self._rows(self._data())
        self.assertEqual([r["name"] for r in rows], ["Epic"])
        row = rows[0]
        self.assertEqual((row["done"], row["total"]), (1, 2))
        self.assertEqual({c["id"] for c in row["children"]}, {child.id, done.id})
        self.assertEqual(row["start"], fields.Date.to_string(self.today))

    def test_epic_without_dates_spans_its_children_or_is_counted_unscheduled(self):
        epic = self.env["project.task"].with_user(self.manager).create({
            "name": "Undated", "project_id": self.project.id, "description": "x",
            "agile_task_type_id": self.epic_type.id, "user_ids": [Command.clear()]})
        empty = self._data()
        self.assertEqual(empty["unscheduled"], 1)
        self.assertEqual(self._rows(empty), [])
        self._issue("Kid", 4, 9, parent=epic)
        row = self._rows(self._data())[0]
        self.assertEqual(row["start"], fields.Date.to_string(self.today + timedelta(days=4)))
        self.assertEqual(row["end"], fields.Date.to_string(self.today + timedelta(days=9)))

    def test_epic_follows_the_sprint_of_its_undated_issues(self):
        """An epic whose issues sit in a sprint but have no dates gets a derived bar (NU-53)."""
        epic = self.env["project.task"].with_user(self.manager).create({
            "name": "Sprint epic", "project_id": self.project.id, "description": "x",
            "agile_task_type_id": self.epic_type.id, "user_ids": [Command.clear()]})
        sprint = self.env["project.sprint"].with_user(self.manager).create({
            "name": "RM sprint", "project_id": self.project.id,
            "date_start": self.today, "date_end": self.today + timedelta(days=13)})
        self.env["project.task"].with_user(self.manager).create({
            "name": "Undated kid", "project_id": self.project.id, "description": "x",
            "parent_id": epic.id, "sprint_id": sprint.id, "user_ids": [Command.clear()]})
        row = next(r for r in self._rows(self._data()) if r["id"] == epic.id)
        self.assertTrue(row["derived"])
        self.assertEqual(row["start"], fields.Date.to_string(self.today))
        self.assertEqual(row["end"], fields.Date.to_string(self.today + timedelta(days=13)))

    def test_issues_without_an_epic_sit_under_no_epic(self):
        self._issue("Loose", 1, 3)
        rows = self._rows(self._data())
        self.assertEqual([r["kind"] for r in rows], ["none"])
        self.assertEqual(rows[0]["children"][0]["name"], "Loose")

    def test_epics_only_and_hide_done(self):
        epic = self._issue("Epic", 0, 10, epic=True)
        done = self._issue("Finished", 1, 2, parent=epic, assigned=True)
        self._issue("Open", 3, 4, parent=epic)
        for step in ("mark_ready", "start", "send_review", "complete"):
            getattr(done.with_user(self.manager), f"action_agile_{step}")()
        self.assertEqual(self._rows(self._data(epics_only=True))[0]["children"], [])
        names = [c["name"] for c in self._rows(self._data(hide_done=True))[0]["children"]]
        self.assertEqual(names, ["Open"])

    def test_late_blocker_marks_arrow_and_both_items(self):
        blocker = self._issue("Blocker", 0, 12)
        blocked = self._issue("Blocked", 5, 9)
        blocked.with_user(self.manager).write({"depend_on_ids": [Command.link(blocker.id)]})
        data = self._data()
        arrow = next(d for d in data["dependencies"] if d["to"] == blocked.id)
        self.assertEqual(arrow["from"], blocker.id)
        self.assertTrue(arrow["late"])
        items = {c["id"]: c for c in self._rows(data)[0]["children"]}
        self.assertTrue(items[blocked.id]["late"])
        self.assertFalse(items[blocker.id]["late"])

    def test_blocker_that_ends_before_the_start_is_not_late(self):
        blocker = self._issue("Early", 0, 3)
        blocked = self._issue("Later", 5, 9)
        blocked.with_user(self.manager).write({"depend_on_ids": [Command.link(blocker.id)]})
        arrow = self._data()["dependencies"][0]
        self.assertFalse(arrow["late"])

    def test_loops_are_found_by_following_blocked_by_links(self):
        # The task model already refuses loops, so imported or hand-edited data is the only way
        # to meet one; the page must still tag it instead of drawing an endless chain.
        graph = {1: {2}, 2: {3}, 3: {1}, 4: {1}}
        self.assertEqual(self.Roadmap._in_loop(graph), {1, 2, 3})
        self.assertEqual(self.Roadmap._in_loop({1: {2}, 2: {3}}), set())

    def test_cross_project_view_groups_by_project_and_labels_dependency(self):
        blocker = self._issue("Other side", 0, 8, project=self.other)
        blocked = self._issue("This side", 4, 6)
        blocked.sudo().write({"depend_on_ids": [Command.link(blocker.id)]})
        data = self._data(self.project | self.other)
        self.assertTrue(data["multi"])
        self.assertEqual({p["name"] for p in data["projects"]}, {self.project.name, self.other.name})
        arrow = data["dependencies"][0]
        self.assertEqual(arrow["from_project"], self.other.name)

    def test_unreadable_blocker_becomes_a_stub_without_key_or_title(self):
        hidden_project = self._project("RMH")
        blocker = self._issue("Secret", 0, 8, project=hidden_project)
        blocked = self._issue("Visible", 4, 6)
        blocked.sudo().write({"depend_on_ids": [Command.link(blocker.id)]})
        self.env["agile.project.member"].sudo().create(
            {"project_id": self.project.id, "user_id": self.outsider.id, "role": "contributor"})
        data = self.env["agile.roadmap"].with_user(self.outsider).roadmap_data([self.project.id])
        stub = data["dependencies"][0]
        self.assertTrue(stub["hidden"])
        self.assertIsNone(stub["from"])
        self.assertNotIn("from_key", stub)
        self.assertNotIn("Secret", str(data))

    def test_outsider_cannot_open_a_project_and_the_picker_skips_it(self):
        with self.assertRaises(AccessError):
            self.env["agile.roadmap"].with_user(self.outsider).roadmap_data([self.project.id])
        picked = self.env["agile.roadmap"].with_user(self.outsider).roadmap_projects()
        self.assertNotIn(self.project.id, [p["id"] for p in picked])

    def test_no_project_is_an_error_and_open_action_checks_access(self):
        with self.assertRaises(UserError):
            self.env["agile.roadmap"].with_user(self.outsider).roadmap_data([])
        action = self.project.with_user(self.manager).action_open_agile_roadmap_page()
        self.assertEqual(action["tag"], "agile_community.roadmap")
        with self.assertRaises(AccessError):
            self.project.with_user(self.outsider).action_open_agile_roadmap_page()

    def test_sprints_and_releases_are_listed(self):
        self.env["project.sprint"].with_user(self.manager).create({
            "name": "Roadmap sprint", "project_id": self.project.id, "date_start": self.today,
            "date_option": "custom", "date_end": self.today + timedelta(days=6)})
        self.env["project.version"].with_user(self.manager).create({
            "name": "R1", "project_id": self.project.id, "release_date": self.today + timedelta(days=30)})
        data = self._data()
        self.assertEqual([s["name"] for s in data["sprints"]], ["Roadmap sprint"])
        self.assertEqual([r["name"] for r in data["releases"]], ["R1"])


class TestAgileBlockers(TestAgileRoadmapPage):
    """P-921: the Blockers panel lists, adds and removes blockers; the tag and sidebar badge follow."""

    def test_blockers_are_listed_with_a_sentence_for_a_late_one(self):
        blocker = self._issue("Blocker", 0, 12)
        blocked = self._issue("Blocked", 5, 9)
        self.Roadmap.add_blocker(blocked.id, blocker.id)
        data = self.Roadmap.blockers(blocked.id)
        self.assertTrue(data["can_edit"])
        self.assertEqual([b["id"] for b in data["blockers"]], [blocker.id])
        self.assertTrue(data["blockers"][0]["late"])
        self.assertIn("7 days after this starts", data["blockers"][0]["sentence"])
        self.assertIn(blocker.issue_key, data["blockers"][0]["sentence"])

    def test_a_blocker_that_ends_first_is_not_late_and_has_a_plain_sentence(self):
        blocker = self._issue("Early", 0, 3)
        blocked = self._issue("Later", 5, 9)
        self.Roadmap.add_blocker(blocked.id, blocker.id)
        entry = self.Roadmap.blockers(blocked.id)["blockers"][0]
        self.assertFalse(entry["late"])
        self.assertNotIn("after this starts", entry["sentence"])

    def test_remove_then_add_again_restores_the_blocker(self):
        blocker = self._issue("B", 0, 3)
        blocked = self._issue("A", 5, 9)
        self.Roadmap.add_blocker(blocked.id, blocker.id)
        self.assertEqual(self.Roadmap.remove_blocker(blocked.id, blocker.id)["blockers"], [])
        self.assertEqual(blocked.depend_on_ids, self.env["project.task"])
        again = self.Roadmap.add_blocker(blocked.id, blocker.id)
        self.assertEqual([b["id"] for b in again["blockers"]], [blocker.id])

    def test_a_loop_is_refused_in_words_directly_and_through_another_issue(self):
        a, b, c = self._issue("A", 0, 2), self._issue("B", 3, 5), self._issue("C", 6, 8)
        self.Roadmap.add_blocker(b.id, a.id)
        self.Roadmap.add_blocker(c.id, b.id)
        with self.assertRaisesRegex(UserError, "already depends on this issue"):
            self.Roadmap.add_blocker(a.id, c.id)
        with self.assertRaisesRegex(UserError, "already depends on this issue"):
            self.Roadmap.add_blocker(a.id, b.id)
        with self.assertRaisesRegex(UserError, "cannot block itself"):
            self.Roadmap.add_blocker(a.id, a.id)

    def test_search_skips_the_issue_its_blockers_and_issues_that_would_make_a_loop(self):
        a, b, c, d = (self._issue(name, 0, 2) for name in ("Alpha", "Beta", "Gamma", "Delta"))
        self.Roadmap.add_blocker(a.id, b.id)
        self.Roadmap.add_blocker(c.id, a.id)
        found = {r["id"] for r in self.Roadmap.search_blockers(a.id, "")}
        self.assertNotIn(a.id, found)
        self.assertNotIn(b.id, found)
        self.assertNotIn(c.id, found)
        self.assertIn(d.id, found)
        self.assertEqual([r["id"] for r in self.Roadmap.search_blockers(a.id, "delta")], [d.id])

    def test_a_blocker_you_cannot_read_is_counted_not_named(self):
        blocked = self._issue("Open", 5, 9)
        secret = self._issue("Secret", 0, 3, project=self.other)
        blocked.sudo().depend_on_ids = [Command.link(secret.id)]
        viewer = self.outsider
        self.env["agile.project.member"].sudo().create(
            {"project_id": self.project.id, "user_id": viewer.id, "role": "contributor"})
        data = self.env["agile.roadmap"].with_user(viewer).blockers(blocked.id)
        self.assertEqual(data["blockers"], [])
        self.assertEqual(data["hidden"], 1)

    def test_a_viewer_sees_the_list_but_cannot_change_it(self):
        blocker = self._issue("B", 0, 3)
        blocked = self._issue("A", 5, 9)
        viewer = self.outsider
        self.env["agile.project.member"].sudo().create(
            {"project_id": self.project.id, "user_id": viewer.id, "role": "stakeholder"})
        roadmap = self.env["agile.roadmap"].with_user(viewer)
        self.assertFalse(roadmap.blockers(blocked.id)["can_edit"])
        with self.assertRaises(AccessError):
            roadmap.add_blocker(blocked.id, blocker.id)

    def test_the_tag_names_open_blockers_only_and_the_sidebar_counts_late_arrows(self):
        done_blocker = self._issue("Finished", 0, 2, assigned=True)
        for step in ("mark_ready", "start", "send_review", "complete"):
            getattr(done_blocker.with_user(self.manager), f"action_agile_{step}")()
        open_one = self._issue("Open one", 0, 12)
        open_two = self._issue("Open two", 0, 3)
        blocked = self._issue("Blocked", 5, 9)
        self.assertFalse(blocked.agile_blocked_by_text)
        for blocker in (done_blocker, open_one, open_two):
            self.Roadmap.add_blocker(blocked.id, blocker.id)
        blocked.invalidate_recordset()
        self.assertEqual(blocked.agile_blocked_by_text, f"{open_one.issue_key} and 1 more")
        self.assertEqual(self.env["agile.roadmap"].late_dependency_count(self.project), 1)
        self.assertEqual(self.project.with_user(self.manager).agile_sidebar_data()["counts"]["late"], 1)

    # ---- O-1073: collision data and Move start ----

    def _date(self, days):
        return fields.Date.to_string(self.today + timedelta(days=days))

    def _complete(self, task):
        for step in ("mark_ready", "start", "send_review", "complete"):
            getattr(task.with_user(self.manager), f"action_agile_{step}")()

    def test_a_blocked_row_carries_its_collision_with_the_earliest_valid_start(self):
        blocker = self._issue("Blocker", 0, 12)
        blocked = self._issue("Blocked", 5, 9)
        self.Roadmap.add_blocker(blocked.id, blocker.id)
        data = self._data()
        self.assertTrue(data["projects"][0]["can_move"])
        rows = {r["id"]: r for r in self._rows(data)[0]["children"]}
        self.assertEqual(rows[blocker.id]["collision"], None)
        self.assertEqual(rows[blocker.id]["blocked_by"], [])
        collision = rows[blocked.id]["collision"]
        self.assertEqual(collision["blocker_key"], blocker.issue_key)
        self.assertEqual(collision["blocker_id"], blocker.id)
        self.assertEqual(collision["days"], 7)
        self.assertEqual(collision["earliest_start"], self._date(13))
        self.assertEqual(collision["new_end"], self._date(17))
        self.assertEqual(rows[blocked.id]["blocked_by"][0]["key"], blocker.issue_key)
        self.assertEqual(self.Roadmap.blockers(blocked.id)["collision"], collision)

    def test_the_blocker_that_ends_last_decides_and_a_blocker_that_ends_first_gives_none(self):
        early, late = self._issue("Early", 0, 6), self._issue("Late", 0, 10)
        blocked = self._issue("Blocked", 5, 9)
        self.Roadmap.add_blocker(blocked.id, early.id)
        self.assertEqual(self.Roadmap.blockers(blocked.id)["collision"]["days"], 1)
        self.Roadmap.add_blocker(blocked.id, late.id)
        collision = self.Roadmap.blockers(blocked.id)["collision"]
        self.assertEqual((collision["blocker_key"], collision["days"]), (late.issue_key, 5))
        ok = self._issue("Fine", 11, 12)
        self.Roadmap.add_blocker(ok.id, early.id)
        self.assertIsNone(self.Roadmap.blockers(ok.id)["collision"])

    def test_a_done_blocker_never_warns(self):
        blocker = self._issue("Finished late", 0, 12, assigned=True)
        blocked = self._issue("Blocked", 5, 9)
        self.Roadmap.add_blocker(blocked.id, blocker.id)
        self._complete(blocker)
        data = self._data()
        self.assertFalse(any(d["late"] for d in data["dependencies"]))
        row = next(c for c in self._rows(data)[0]["children"] if c["id"] == blocked.id)
        self.assertFalse(row["late"])
        self.assertIsNone(row["collision"])
        self.assertEqual(row["blocked_by"], [])
        panel = self.Roadmap.blockers(blocked.id)
        self.assertIsNone(panel["collision"])
        self.assertFalse(panel["blockers"][0]["late"])

    def test_move_start_keeps_the_length_and_undo_puts_it_back(self):
        blocker = self._issue("Blocker", 0, 12)
        blocked = self._issue("Blocked", 5, 9)
        self.Roadmap.add_blocker(blocked.id, blocker.id)
        moved = self.Roadmap.move_to_earliest_start(blocked.id, self._date(5))
        self.assertEqual(moved["old"], {"start": self._date(5), "end": self._date(9)})
        self.assertEqual(moved["new"], {"start": self._date(13), "end": self._date(17)})
        blocked.invalidate_recordset()
        self.assertEqual(fields.Date.to_string(blocked.agile_planned_start), self._date(13))
        self.assertEqual(fields.Date.to_string(blocked.agile_planned_end), self._date(17))
        self.assertIsNone(moved["panel"]["collision"])
        restored = self.Roadmap.undo_move_start(blocked.id, self._date(5), self._date(9), self._date(13))
        blocked.invalidate_recordset()
        self.assertEqual(fields.Date.to_string(blocked.agile_planned_start), self._date(5))
        self.assertEqual(restored["collision"]["days"], 7)

    def test_move_start_refuses_a_stale_view_and_a_change_made_after_the_move(self):
        blocker = self._issue("Blocker", 0, 12)
        blocked = self._issue("Blocked", 5, 9)
        self.Roadmap.add_blocker(blocked.id, blocker.id)
        with self.assertRaisesRegex(UserError, "changed by someone else"):
            self.Roadmap.move_to_earliest_start(blocked.id, self._date(4))
        self.Roadmap.move_to_earliest_start(blocked.id, self._date(5))
        blocked.with_user(self.manager).write({"agile_planned_start": self.today + timedelta(days=14)})
        with self.assertRaisesRegex(UserError, "not put back"):
            self.Roadmap.undo_move_start(blocked.id, self._date(5), self._date(9), self._date(13))
        blocked.invalidate_recordset()
        self.assertEqual(fields.Date.to_string(blocked.agile_planned_start), self._date(14))

    def test_move_start_with_nothing_to_move_says_so(self):
        blocker = self._issue("Early", 0, 3)
        blocked = self._issue("Later", 5, 9)
        self.Roadmap.add_blocker(blocked.id, blocker.id)
        with self.assertRaisesRegex(UserError, "Nothing to move"):
            self.Roadmap.move_to_earliest_start(blocked.id, self._date(5))

    def test_move_start_will_not_take_an_issue_outside_its_epic(self):
        epic = self._issue("Epic", 0, 10, epic=True)
        kid = self._issue("Kid", 5, 9, parent=epic)
        blocker = self._issue("Blocker", 0, 12)
        self.Roadmap.add_blocker(kid.id, blocker.id)
        with self.assertRaisesRegex(UserError, "outside its epic"):
            self.Roadmap.move_to_earliest_start(kid.id, self._date(5))
        kid.invalidate_recordset()
        self.assertEqual(fields.Date.to_string(kid.agile_planned_start), self._date(5))

    def test_only_who_may_set_roadmap_dates_can_move_a_start(self):
        blocker = self._issue("Blocker", 0, 12)
        blocked = self._issue("Blocked", 5, 9)
        self.Roadmap.add_blocker(blocked.id, blocker.id)
        self.assertTrue(self.Roadmap.blockers(blocked.id)["can_move"])
        self.env["agile.project.member"].sudo().create(
            {"project_id": self.project.id, "user_id": self.outsider.id, "role": "contributor"})
        roadmap = self.env["agile.roadmap"].with_user(self.outsider)
        self.assertFalse(roadmap.blockers(blocked.id)["can_move"])
        with self.assertRaises(AccessError):
            roadmap.move_to_earliest_start(blocked.id, self._date(5))
        blocked.invalidate_recordset()
        self.assertEqual(fields.Date.to_string(blocked.agile_planned_start), self._date(5))

    # ---- O-1074: CSV export ----

    def _csv(self, **kwargs):
        import csv
        import io
        result = self.Roadmap.roadmap_csv([self.project.id], **kwargs)
        return result, list(csv.reader(io.StringIO(result["content"])))

    def test_csv_has_one_line_for_each_readable_item_with_collision_columns(self):
        epic = self._issue("Epic", 0, 20, epic=True)
        blocker = self._issue("Blocker", 0, 12, parent=epic)
        blocked = self._issue("Blocked", 5, 9, parent=epic)
        self.Roadmap.add_blocker(blocked.id, blocker.id)
        result, rows = self._csv()
        self.assertEqual(result["filename"], "roadmap-roadmap-rma.csv")
        self.assertEqual(rows[0][:3], ["Project", "Key", "Title"])
        self.assertEqual(rows[0][7:], ["Blocked by", "Collision days", "Earliest valid start"])
        by_key = {r[1]: r for r in rows[1:]}
        self.assertEqual(len(rows) - 1, 3)
        line = by_key[blocked.issue_key]
        self.assertEqual(line[0], self.project.name)
        self.assertEqual(line[2], "Blocked")
        self.assertEqual((line[5], line[6]), (self._date(5), self._date(9)))
        self.assertEqual((line[7], line[8], line[9]), (blocker.issue_key, "7", self._date(13)))
        self.assertEqual(by_key[blocker.issue_key][7:], ["", "", ""])
        self.assertEqual(by_key[epic.issue_key][3], "Epic")

    def test_csv_follows_the_screen_filters_and_neutralises_formulas(self):
        epic = self._issue("Epic", 0, 20, epic=True)
        self._issue("=SUM(A1)", 1, 3, parent=epic)
        self.assertEqual(len(self._csv()[1]) - 1, 2)
        self.assertEqual(len(self._csv(epics_only=True)[1]) - 1, 1)
        titles = [r[2] for r in self._csv()[1][1:]]
        self.assertIn("'=SUM(A1)", titles)

    def test_csv_leaves_out_what_the_person_cannot_read_and_can_be_empty(self):
        hidden = self._project("RMX")
        blocker = self._issue("Secret blocker", 0, 8, project=hidden)
        blocked = self._issue("Visible", 4, 6)
        blocked.sudo().write({"depend_on_ids": [Command.link(blocker.id)]})
        self.env["agile.project.member"].sudo().create(
            {"project_id": self.project.id, "user_id": self.outsider.id, "role": "contributor"})
        result = self.env["agile.roadmap"].with_user(self.outsider).roadmap_csv([self.project.id])
        self.assertNotIn("Secret", result["content"])
        self.assertNotIn(blocker.issue_key, result["content"])
        self.assertEqual(result["count"], 1)
        with self.assertRaises(AccessError):
            self.env["agile.roadmap"].with_user(self.outsider).roadmap_csv([hidden.id])
        empty = self.Roadmap.roadmap_csv([self.other.id])
        self.assertEqual(empty["count"], 0)
        self.assertEqual(empty["content"].count("\n"), 1)


class TestAgileRollup(TestAgileRoadmapPage):
    """P-922: each project heading carries epic and issue progress."""

    def _finish(self, issue):
        issue.write({"user_ids": [Command.set([self.manager.id])]})
        for step in ("mark_ready", "start", "send_review", "complete"):
            getattr(issue.with_user(self.manager), f"action_agile_{step}")()

    def test_rollup_counts_epics_and_issues_per_project(self):
        epic = self._issue("Epic", 0, 20, epic=True)
        done = self._issue("Done", 1, 3, parent=epic)
        self._issue("Open", 4, 6, parent=epic)
        self._finish(done)
        self._issue("Elsewhere", 0, 4, project=self.other)
        data = self._data(self.project | self.other)
        by_name = {p["name"]: p["rollup"] for p in data["projects"]}
        self.assertEqual(by_name[self.project.name], {
            "epics_total": 1, "epics_done": 0, "issues_total": 2, "issues_done": 1})
        self.assertEqual(by_name[self.other.name]["issues_total"], 1)
        self.assertEqual(by_name[self.other.name]["issues_done"], 0)

    def test_rollup_ignores_work_in_projects_the_person_cannot_read(self):
        self._issue("Hidden work", 0, 4, project=self.other)
        self.env["agile.project.member"].sudo().create(
            {"project_id": self.project.id, "user_id": self.outsider.id, "role": "contributor"})
        data = self.env["agile.roadmap"].with_user(self.outsider).roadmap_data([])
        self.assertEqual([p["name"] for p in data["projects"]], [self.project.name])
