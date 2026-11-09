import csv
import io
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user

from odoo.addons.agile_community.models.agile_query import AgileQuery, QueryError


class TestAgileFilter(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, login="fl_manager", groups="project.group_project_manager")
        cls.alice = new_test_user(cls.env, login="fl_alice", name="Alice Filter", groups="project.group_project_user")
        cls.bob = new_test_user(cls.env, login="fl_bob", name="Bob Filter", groups="project.group_project_user")
        cls.outsider = new_test_user(cls.env, login="fl_out", groups="project.group_project_user")
        cls.project = cls.env["project.project"].with_user(cls.manager).create({
            "name": "Filter project", "privacy_visibility": "employees", "agile_enabled": True, "agile_key": "FLT",
        })
        for user in (cls.alice, cls.bob):
            member = cls.env["agile.project.member"].search([
                ("project_id", "=", cls.project.id), ("user_id", "=", user.id)])
            if member:
                member.with_user(cls.manager).role = "contributor"
            else:
                cls.env["agile.project.member"].with_user(cls.manager).create({
                    "project_id": cls.project.id, "user_id": user.id, "role": "contributor"})
        cls.env["agile.project.member"].sudo().search([
            ("project_id", "=", cls.project.id), ("user_id", "=", cls.outsider.id)]).unlink()
        bug = cls.env.ref("agile_community.agile_task_type_bug")
        cls.sprint = cls.env["project.sprint"].sudo().create({
            "name": "Sprint 1", "project_id": cls.project.id,
            "date_start": fields.Date.today(), "date_end": fields.Date.today() + timedelta(days=10),
        })
        cls.tag = cls.env["project.tags"].create({"name": "urgent-fix"})
        Task = cls.env["project.task"].with_user(cls.manager)
        cls.t_bug = Task.create({
            "name": "Login fails", "project_id": cls.project.id, "agile_task_type_id": bug.id,
            "user_ids": [Command.set([cls.alice.id])], "priority": "2", "tag_ids": [Command.set([cls.tag.id])],
            "description": "<p>Cannot sign in with SSO</p>",
        })
        cls.t_task = Task.create({
            "name": "Write docs", "project_id": cls.project.id, "user_ids": [Command.set([cls.bob.id])],
        })
        cls.t_free = Task.create({"name": "Unowned", "project_id": cls.project.id, "user_ids": [Command.clear()]})
        cls.t_free.sudo().write({"sprint_id": cls.sprint.id})

    def _tool(self, user=None):
        return AgileQuery(self.env(user=user) if user else self.env, self.project)

    def _find(self, text, user=None):
        domain, _words = self._tool(user).compile(text)
        env = self.env(user=user) if user else self.env
        return env["project.task"].search([("project_id", "=", self.project.id), ("agile_issue", "=", True)] + domain)

    # ---- S-302: the language ----

    def test_conditions_find_the_right_issues(self):
        self.assertEqual(self._find('type = Bug'), self.t_bug)
        self.assertEqual(self._find('assignee = "Bob Filter"'), self.t_task)
        self.assertEqual(self._find("assignee = unassigned"), self.t_free)
        self.assertEqual(self._find("assignee = me", user=self.alice), self.t_bug)
        self.assertEqual(self._find("label = urgent-fix"), self.t_bug)
        self.assertEqual(self._find("priority = High"), self.t_bug)
        self.assertEqual(self._find("sprint = Sprint 1".replace("Sprint 1", '"Sprint 1"')), self.t_free)
        self.assertEqual(self._find("text ~ sso"), self.t_bug, "the description is searched too")
        self.assertEqual(self._find('text ~ "docs"'), self.t_task)
        self.assertEqual(self._find("key = %s" % self.t_bug.issue_key), self.t_bug)
        self.assertEqual(self._find("sprint IS EMPTY") , self.t_bug | self.t_task)
        self.assertEqual(self._find("assignee IN (me, Bob)".replace("Bob", '"Bob Filter"'), user=self.alice),
                         self.t_bug | self.t_task)

    def test_and_or_not_and_brackets(self):
        self.assertEqual(self._find("type = Bug OR text ~ docs"), self.t_bug | self.t_task)
        self.assertEqual(self._find("(type = Bug OR text ~ docs) AND assignee != unassigned AND NOT text ~ login"),
                         self.t_task)
        self.assertEqual(self._find("type = Bug and text ~ login"), self.t_bug, "keywords ignore case")
        self.assertEqual(self._find("statusCategory = Ready AND NOT sprint IS EMPTY"), self.t_free)

    def test_current_sprint_and_dates_and_numbers(self):
        self.assertEqual(self._find("sprint = openSprints"), self.t_free, "the sprint is still planned")
        self.assertFalse(self._find("sprint = currentSprint"), "no sprint has started")
        self.assertEqual(self._find("created >= -1d"), self.t_bug | self.t_task | self.t_free)
        self.assertFalse(self._find("created < -7d"))
        self.assertFalse(self._find("due <= today"))
        self.assertEqual(self._find("due IS EMPTY"), self.t_bug | self.t_task | self.t_free)
        self.t_task.sudo().story_points = 5
        self.assertEqual(self._find("points > 3"), self.t_task)
        self.assertEqual(self._find("points IS EMPTY"), self.t_bug | self.t_free)

    def test_words_describe_the_query(self):
        _domain, words = self._tool().compile('status = Backlog AND assignee = me')
        self.assertEqual(words, "Status is Backlog, and Assignee is you")
        _domain, words = self._tool().compile("type = Bug OR (assignee = me AND points > 2)")
        self.assertIn("Story points is above 2", words)
        self.assertTrue(words.startswith("Type is Bug, or ("))

    def test_errors_say_what_is_wrong(self):
        cases = {
            "statu = Done": "Did you mean 'status'?",
            'status = "Nowhere"': "is not one of this project's statuses",
            "assignee < me": "'<' does not work with assignee",
            "(type = Bug": "closing bracket is missing",
            "type = Bug)": "closing bracket has no opening",
            'type = "Bug': "quote is not closed",
            "type = Bug status = Done": "Join conditions with AND or OR",
            "type = Bug AND": "stops too early",
            "": "Write a condition",
            "priority = Huge": "is not a priority",
            "created > yesterday": "is not a date",
            "points > many": "is not a number",
            "type Bug": "Add an operator",
            "type ! Bug": "not allowed here",
            "assignee = Nobody": "is not one of this project's people",
        }
        for text, expected in cases.items():
            with self.assertRaises(QueryError, msg=text) as caught:
                self._tool().compile(text)
            self.assertIn(expected, caught.exception.message, text)
        with self.assertRaises(QueryError) as caught:
            self._tool().compile("type = Bug AND statu = Done")
        self.assertEqual((caught.exception.start, caught.exception.end), (15, 20), "points at the bad word")

    def test_text_is_never_code(self):
        for hostile in (
            "text ~ \"'; DROP TABLE project_task; --\"",
            "__import__('os').system('id')",
            "text ~ \"%s\" OR 1=1",
            "type = Bug; DELETE",
        ):
            try:
                domain, _words = self._tool().compile(hostile)
            except QueryError:
                continue
            self.env["project.task"].search(domain)  # compiled values are data, so this is a harmless search
        self.assertTrue(self.env["project.task"].search_count([("id", "=", self.t_bug.id)]))

    def test_filters_search_one_project_only(self):
        other = self.env["project.project"].with_user(self.manager).create({
            "name": "Other", "privacy_visibility": "employees", "agile_enabled": True, "agile_key": "OTX"})
        other_task = self.env["project.task"].with_user(self.manager).create({"name": "Login elsewhere", "project_id": other.id})
        self.assertNotIn(other_task, self._find("text ~ login"))
        with self.assertRaises(QueryError):
            self._tool().compile('project = "Other"')
        self.assertEqual(self._find('project = "Filter project" AND type = Bug'), self.t_bug)

    def test_suggestions_follow_the_grammar(self):
        def labels(text, cursor=None):
            return [i["label"] for i in self._tool().suggest(text, cursor)["items"]]
        self.assertIn("status", labels(""))
        self.assertEqual(labels("sta"), ["status", "statusCategory"])
        self.assertIn("IS EMPTY", labels("assignee "))
        self.assertNotIn("<", labels("assignee "))
        self.assertIn("<", labels("points "))
        self.assertIn("Bug", labels("type = "))
        self.assertIn("me", labels("assignee = "))
        self.assertEqual(labels('type = Bug '), ["AND", "OR", "ORDER BY"])
        self.assertIn("status", labels("type = Bug AND "))
        self.assertIn("(", labels("assignee IN "))
        self.assertIn("me", labels("assignee IN ("))
        self.assertEqual(labels("assignee IN (me "), [",", ")"])
        self.assertIn(")", labels("(type = Bug "))
        self.assertIn('"In Progress"', labels("status = "))
        self.assertEqual(self._tool().suggest("type = B", 8)["start"], 7)
        self.assertIn("Done", labels("statusCategory = "))
        self.assertEqual(labels("zzz"), [])

    # ---- S-301: saved filters ----

    def _filter(self, user, **vals):
        return self.env["agile.filter"].with_user(user).create({
            "name": "F", "project_id": self.project.id, "query": "type = Bug", **vals})

    def test_private_and_shared_filters(self):
        private = self._filter(self.alice, name="Mine")
        shared = self._filter(self.alice, name="Team", visibility="shared")
        seen = self.env["agile.filter"].with_user(self.bob).search([("project_id", "=", self.project.id)])
        self.assertEqual(seen, shared, "a private filter is for its owner only")
        self.assertEqual(self.env["agile.filter"].with_user(self.manager).search([("id", "=", private.id)]),
                         self.env["agile.filter"], "managers do not see private filters")
        with self.assertRaises(AccessError):
            shared.with_user(self.bob).write({"name": "Mine now"})
        shared.with_user(self.manager).write({"name": "Team (renamed)"})
        shared.with_user(self.alice).write({"query": "type = Story"})
        with self.assertRaises(AccessError):
            shared.with_user(self.bob).unlink()
        with self.assertRaises(AccessError):
            self.env["agile.filter"].with_user(self.outsider).create(
                {"name": "x", "project_id": self.project.id, "query": "type = Bug"})
        self.assertFalse(self.env["agile.filter"].with_user(self.outsider).search([("id", "=", shared.id)]))
        shared.with_user(self.alice).unlink()

    def test_an_invalid_query_cannot_be_saved(self):
        with self.assertRaises(ValidationError) as caught:
            self._filter(self.alice, query="statu = Done")
        self.assertIn("Did you mean 'status'?", str(caught.exception))
        saved = self._filter(self.alice)
        with self.assertRaises(ValidationError):
            saved.query = "type ="

    def test_results_count_and_copy(self):
        saved = self._filter(self.alice, query="assignee = me")
        self.assertEqual(saved.match_count, 1)
        action = saved.action_open_results()
        self.assertEqual(action["name"], "F")
        self.assertNotIn("search_default_agile_hide_completed", action["context"])
        found = self.env["project.task"].with_user(self.alice).search(action["domain"])
        self.assertEqual(found, self.t_bug)
        copy_id = saved.action_save_copy()["res_id"]
        copy = self.env["agile.filter"].browse(copy_id)
        self.assertEqual((copy.visibility, copy.owner_id), ("private", self.alice))

    def test_shared_me_resolves_for_each_viewer(self):
        shared = self._filter(self.alice, visibility="shared", query="assignee = me")
        self.assertEqual(shared.with_user(self.alice).match_count, 1)
        self.assertEqual(shared.with_user(self.bob).match_count, 1)
        self.assertEqual(self.env["project.task"].with_user(self.bob).search(
            shared.with_user(self.bob)._issue_domain()), self.t_task)

    def test_the_query_bar_assist_call(self):
        Filter = self.env["agile.filter"].with_user(self.alice)
        good = Filter.agile_query_assist(self.project.id, "type = Bug", 10)
        self.assertTrue(good["ok"])
        self.assertEqual(good["count"], 1)
        bad = Filter.agile_query_assist(self.project.id, "statu = Done", 4)
        self.assertFalse(bad["ok"])
        self.assertIn("Did you mean", bad["error"]["message"])
        self.assertIn("status", [i["label"] for i in bad["suggest"]["items"]])
        self.assertIsNone(Filter.agile_query_assist(self.project.id, "", 0)["count"])
        with self.assertRaises(AccessError):
            self.env["agile.filter"].with_user(self.outsider).agile_query_assist(self.project.id, "type = Bug")

    # ---- S-303: export and digest ----

    def test_export_respects_rights_and_guards_formulas(self):
        self.t_free.sudo().name = "=HYPERLINK(\"http://x\")"
        saved = self._filter(self.alice, query="text ~ HYPERLINK", visibility="shared")
        rows = list(csv.reader(io.StringIO(saved._export_csv())))
        self.assertEqual(rows[0][:3], ["Key", "Title", "Type"])
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[1][1].startswith("'="), "a formula is written as text")
        outsider_rows = self.env["agile.filter"].with_user(self.outsider)
        with self.assertRaises(AccessError):
            outsider_rows.browse(saved.id)._export_csv()
        saved.query = "type = Bug"
        self.assertEqual(list(csv.reader(io.StringIO(saved.with_user(self.bob)._export_csv())))[1][0], self.t_bug.issue_key)

    def test_digest_is_sent_to_subscribers_with_their_own_view(self):
        shared = self._filter(self.alice, visibility="shared", query="assignee = me")
        shared.with_user(self.alice).my_digest = "daily"
        shared.with_user(self.bob).my_digest = "weekly"
        self.assertEqual(shared.with_user(self.bob).my_digest, "weekly")
        self.assertEqual(len(shared.sudo().subscription_ids), 2)
        mails_before = self.env["mail.mail"].search([]).ids
        self.env["agile.filter"]._cron_send_digests()
        mails = self.env["mail.mail"].search([("id", "not in", mails_before)])
        self.assertEqual(len(mails), 2)
        by_user = {m.email_to: m.body_html for m in mails}
        alice_mail = next(b for to, b in by_user.items() if "Alice" in to)
        self.assertIn("Login fails", alice_mail)
        self.assertNotIn("Write docs", alice_mail)
        self.assertIn("Write docs", next(b for to, b in by_user.items() if "Bob" in to))
        # Not due again straight away.
        self.env["agile.filter"]._cron_send_digests()
        self.assertEqual(len(self.env["mail.mail"].search([("id", "not in", mails_before)])), 2)
        shared.with_user(self.alice).my_digest = "none"
        self.assertEqual(len(shared.sudo().subscription_ids), 1)

    def test_digest_stays_quiet_when_empty_and_when_access_is_lost(self):
        quiet = self._filter(self.alice, query="priority = Urgent")
        quiet.with_user(self.alice).my_digest = "daily"
        mails_before = self.env["mail.mail"].search([]).ids
        self.env["agile.filter"]._cron_send_digests()
        self.assertFalse(self.env["mail.mail"].search([("id", "not in", mails_before)]))
        quiet.subscription_ids.write({"send_empty": True, "last_sent": False})
        self.env["agile.filter"]._cron_send_digests()
        self.assertEqual(len(self.env["mail.mail"].search([("id", "not in", mails_before)])), 1)
        quiet.subscription_ids.write({"last_sent": False})
        self.env["agile.project.member"].sudo().search([
            ("project_id", "=", self.project.id), ("user_id", "=", self.alice.id)]).unlink()
        before = self.env["mail.mail"].search_count([])
        self.env["agile.filter"]._cron_send_digests()
        self.assertEqual(self.env["mail.mail"].search_count([]), before, "no mail once the person left the project")

    # ---- Basic rows and the saved-filter search field ----

    def test_basic_rows_follow_the_query(self):
        tool = self._tool()
        rows = tool.to_rows('status = "In Progress" AND assignee != me AND due < -7d AND sprint IS EMPTY')
        self.assertFalse(rows["match_any"])
        self.assertEqual(
            [(r["field"], r["op"], r["value"]) for r in rows["rows"]],
            [("status", "=", "In Progress"), ("assignee", "!=", "me"), ("due", "<", "-7d"), ("sprint", "IS EMPTY", "")],
        )
        self.assertTrue(tool.to_rows("type = Bug OR type = Story")["match_any"])
        self.assertEqual(tool.to_rows("type = Bug")["rows"][0]["value"], "Bug")
        for beyond_basic in (
            "(type = Bug OR text ~ a) AND assignee = me", "NOT type = Bug", "assignee IN (me)",
            "type = Bug AND priority = High", "type = Bug OR type = Story AND text ~ a", "type =", "",
        ):
            self.assertIsNone(tool.to_rows(beyond_basic), beyond_basic)

    def test_basic_options_list_values_and_operators(self):
        options = {o["field"]: o for o in self._tool().basic_options()}
        self.assertEqual(list(options)[:3], ["status", "assignee", "sprint"])
        self.assertIn("In Progress", options["status"]["values"])
        self.assertIn("me", options["assignee"]["values"])
        self.assertIsNone(options["due"]["values"])
        self.assertEqual([o["label"] for o in options["due"]["ops"]][:2], ["is", "is not"])
        self.assertIn("is before", [o["label"] for o in options["due"]["ops"]])
        self.assertNotIn("<", [o["op"] for o in options["assignee"]["ops"]])
        self.assertEqual(self.env["agile.filter"].with_user(self.alice).agile_query_options(self.project.id), self.env["agile.filter"].with_user(self.alice).agile_query_options(self.project.id))
        with self.assertRaises(AccessError):
            self.env["agile.filter"].with_user(self.outsider).agile_query_options(self.project.id)
        result = self.env["agile.filter"].with_user(self.alice).agile_query_assist(self.project.id, "type = Bug", 10)
        self.assertEqual(result["rows"]["rows"][0]["field"], "type")

    def test_saved_filter_works_in_the_search_box(self):
        Task = self.env["project.task"]
        shared = self._filter(self.alice, visibility="shared", query="assignee = me", name="Mine to do")
        private = self._filter(self.alice, query="type = Bug", name="Only bugs")
        as_bob = Task.with_user(self.bob)
        self.assertEqual(as_bob.search([("agile_saved_filter_id", "=", shared.id)]), self.t_task, "me is read for Bob")
        self.assertEqual(
            Task.with_user(self.alice).search([("agile_saved_filter_id", "in", [shared.id, private.id])]), self.t_bug)
        self.assertEqual(Task.with_user(self.alice).search([("agile_saved_filter_id", "ilike", "only")]), self.t_bug)
        self.assertIn(self.t_bug, Task.search([("agile_saved_filter_id", "=", False)]))
        # A private filter of someone else finds nothing for Bob: it is not his to read.
        self.assertFalse(as_bob.search([("agile_saved_filter_id", "=", private.id)]))
        combined = Task.with_user(self.alice).search(
            [("agile_saved_filter_id", "=", shared.id), ("priority", "=", "2")])
        self.assertEqual(combined, self.t_bug)

    def test_order_send_empty_and_more_count(self):
        saved = self._filter(self.alice, query="text ~ o", visibility="shared")
        self.assertEqual(saved._issues().mapped("id"), sorted(saved._issues().mapped("id")), "rank order by default")
        saved.write({"order_by": "priority", "order_direction": "desc"})
        self.assertEqual(saved._issues()[0], self.t_bug, "High priority first")
        saved.write({"order_by": "updated", "order_direction": "asc"})
        self.assertTrue(saved._issues())
        rows = list(csv.reader(io.StringIO(saved._export_csv())))
        saved.write({"order_by": "priority", "order_direction": "desc"})
        self.assertEqual(list(csv.reader(io.StringIO(saved._export_csv())))[1][0], self.t_bug.issue_key)
        self.assertTrue(rows)
        # Send even when empty is a per-person switch on the form.
        quiet = self._filter(self.alice, query="priority = Urgent")
        mine = quiet.with_user(self.alice)
        mine.my_digest = "daily"
        mine.my_send_empty = True
        self.assertTrue(mine.my_send_empty)
        self.assertTrue(quiet.sudo().subscription_ids.send_empty)
        before = self.env["mail.mail"].search_count([])
        self.env["agile.filter"]._cron_send_digests()
        self.assertEqual(self.env["mail.mail"].search_count([]), before + 1)
        # More than 50 issues: the mail says how many are not shown.
        Task = self.env["project.task"].with_user(self.manager)
        for index in range(52):
            Task.create({"name": f"Bulk {index}", "project_id": self.project.id})
        big = self._filter(self.alice, query="text ~ Bulk")
        big.with_user(self.alice).my_digest = "daily"
        ids_before = self.env["mail.mail"].search([]).ids
        self.env["agile.filter"]._cron_send_digests()
        mail = self.env["mail.mail"].search([("id", "not in", ids_before)])
        self.assertIn("2 more", mail.body_html)


class TestAgileQueryOrder(TestAgileFilter):
    """ORDER BY in the query language (K-1031)."""

    def _ordered(self, text, user=None):
        domain, _words = self._tool(user).compile(text)
        order = self._tool(user).order(text)
        env = self.env(user=user) if user else self.env
        return env["project.task"].search(
            [("project_id", "=", self.project.id), ("agile_issue", "=", True)] + domain, order=f"{order}, id")

    def test_sorts_by_priority_and_falls_back_to_the_key(self):
        found = self._ordered("ORDER BY priority DESC")
        self.assertEqual(found[0], self.t_bug, "High comes before the unprioritised ones")
        self.assertEqual(self._ordered("priority = High ORDER BY updated"), self.t_bug)
        self.assertEqual(self._ordered("ORDER BY key DESC")[0], self.t_free)
        self.assertEqual(self._ordered("ORDER BY key")[0], self.t_bug)

    def test_a_key_written_without_leading_zeros_finds_the_issue(self):
        """E2E-008: keys are stored zero-padded (FLT-0001); people write FLT-1."""
        key = self.t_bug.issue_key
        prefix, number = key.rsplit("-", 1)
        self.assertEqual(self._find(f"key = {prefix}-{int(number)}"), self.t_bug)
        self.assertEqual(self._find(f"key = {prefix.lower()}-{int(number)}"), self.t_bug)
        self.assertEqual(self._find(f"key IN ({prefix}-{int(number)}, {self.t_task.issue_key})"), self.t_bug | self.t_task)
        self.assertNotIn(self.t_bug, self._find(f"key != {prefix}-{int(number)}"))

    def test_percent_and_underscore_are_plain_characters(self):
        """E2E-009: text ~ "%" must not act as a SQL wildcard."""
        self.assertFalse(self._find('text ~ "%"'))
        self.assertFalse(self._find('text ~ "_"'))
        self.t_task.name = "Write docs 100% done_now"
        self.assertEqual(self._find('text ~ "100%"'), self.t_task)
        self.assertEqual(self._find('text ~ "done_now"'), self.t_task)
        self.assertFalse(self._find('key ~ "%"'))

    def test_several_keys_and_a_quoted_word(self):
        tool = self._tool()
        self.assertEqual(
            tool.order("ORDER BY priority DESC, updated ASC"),
            "priority desc nulls last, write_date asc nulls last")
        self.assertEqual(tool.order('text ~ "order by" ORDER BY title'), "name asc nulls last")
        self.assertEqual(tool.order("status = Done"), "")

    def test_the_words_say_how_the_results_are_sorted(self):
        _domain, words = self._tool().compile("type = Bug ORDER BY priority DESC")
        self.assertIn("sorted by Priority descending", words)
        self.assertEqual(self._tool().to_rows("type = Bug ORDER BY priority")["sort"], "ORDER BY priority")
        self.assertIsNotNone(self._tool().to_rows("type = Bug"))

    def test_basic_names_what_it_cannot_show_and_keeps_a_lone_sort(self):
        tool = self._tool()
        self.assertEqual(tool.to_rows("ORDER BY priority DESC"), {"match_any": False, "rows": [], "sort": "ORDER BY priority DESC"})
        self.assertEqual(tool.basic_blockers("ORDER BY priority DESC"), [])
        self.assertEqual(tool.basic_blockers("type = Bug ORDER BY priority"), [])
        self.assertEqual(tool.basic_blockers("(type = Bug OR text ~ a) AND assignee = me"), ["brackets"])
        self.assertEqual(tool.basic_blockers("NOT type = Bug"), ["NOT"])
        self.assertIn("IN", tool.basic_blockers("assignee IN (me)"))
        self.assertEqual(tool.basic_blockers("status CHANGED")[0][:7], "history")

    def test_a_bad_sort_key_says_what_to_use(self):
        for text, fragment in (
            ("ORDER BY colour", "cannot be sorted"),
            ("ORDER BY", "Say what to sort by"),
            ("ORDER BY priority updated", "Separate sort keys"),
        ):
            with self.assertRaises(QueryError) as caught:
                self._tool().compile(text)
            self.assertIn(fragment, caught.exception.message)

    def test_a_saved_filter_sorts_its_export_by_its_query(self):
        saved = self._filter(self.alice, query="ORDER BY key DESC")
        self.assertEqual(saved.with_user(self.alice)._issues()[0], self.t_free)
        self.assertEqual(saved.with_user(self.alice)._issue_domain()[:2], [
            ("project_id", "=", self.project.id), ("agile_issue", "=", True)])

    def test_autocomplete_offers_order_by_and_the_sort_keys(self):
        tool = self._tool()
        labels = lambda text: [i["label"] for i in tool.suggest(text)["items"]]  # noqa: E731
        self.assertIn("ORDER BY", labels("status = Done "))
        self.assertIn("priority", labels("status = Done ORDER BY "))
        self.assertEqual(labels("status = Done ORDER BY priority "), ["ASC", "DESC", ","])


class TestAgileQueryFunctions(TestAgileFilter):
    """User and date functions in the query language (K-1033)."""

    def test_current_user_and_members_of(self):
        self.assertEqual(self._find("assignee = currentUser()", user=self.alice), self.t_bug)
        self.assertEqual(self._find("assignee = currentUser", user=self.bob), self.t_task)
        self.assertEqual(self._find("assignee = membersOf()"), self.t_bug | self.t_task,
                         "everyone on the Agile team, nobody unassigned")
        self.assertEqual(self._find("assignee != membersOf()"), self.t_free)
        _domain, words = self._tool().compile("assignee = currentUser() AND reporter = membersOf()")
        self.assertEqual(words, "Assignee is you, and Reporter is the team")

    def test_date_functions_resolve_to_dates(self):
        today = fields.Date.context_today(self.env["project.task"])
        tool = self._tool()
        monday = today - timedelta(days=today.weekday())
        expected = {
            "startOfWeek": monday, "endOfWeek": monday + timedelta(days=6),
            "startOfMonth": today.replace(day=1), "endOfMonth": today + relativedelta(day=31),
            "-1m": today - relativedelta(months=1),
        }
        for text, day in expected.items():
            domain, _words = tool.compile(f"due = {text}()" if text[0] != "-" else f"due = {text}")
            self.assertEqual(domain, [("date_deadline", "=", day.isoformat())], text)

    def test_date_functions_filter_issues(self):
        today = fields.Date.context_today(self.env["project.task"])
        self.t_bug.sudo().date_deadline = today.replace(day=1)
        self.t_task.sudo().date_deadline = today + relativedelta(day=31)
        self.assertEqual(self._find("due >= startOfMonth AND due <= endOfMonth"), self.t_bug | self.t_task)
        self.assertEqual(self._find("due = startOfMonth()"), self.t_bug)
        self.assertEqual(self._find("created >= startOfMonth()"), self.t_bug | self.t_task | self.t_free)

    def test_bad_date_names_the_new_choices(self):
        with self.assertRaises(Exception) as caught:
            self._tool().compile("due = endOfYear")
        self.assertIn("startOfWeek", str(caught.exception))

    def test_functions_are_offered_as_shortcuts(self):
        def labels(text):
            return [i["label"] for i in self._tool().suggest(text, len(text))["items"]]
        self.assertIn("currentUser", labels("assignee = "))
        self.assertIn("membersOf", labels("assignee = "))
        self.assertIn("endOfMonth", labels("due < "))


class TestAgileQueryHistory(TestAgileFilter):
    """WAS and CHANGED, read from the chatter's tracked changes (K-1034)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        stages = cls.project.type_ids.filtered("agile_status")
        cls.review = stages.filtered(lambda s: s.agile_status == "review")[:1] or stages[-1]
        cls.todo = stages.filtered(lambda s: s.agile_status == "ready")[:1] or stages[0]
        # Tracking is discarded for a record created in the same transaction until the creation is committed.
        cls.env.cr.precommit.run()
        # t_bug went through Review and came back; t_task changed hands; t_free was never touched
        cls.t_bug.with_user(cls.alice).sudo().stage_id = cls.review
        cls.env.flush_all()
        cls.env.cr.precommit.run()  # one tracked change at a time, as in separate requests
        cls.t_bug.with_user(cls.alice).sudo().stage_id = cls.todo
        cls.env.flush_all()
        cls.env.cr.precommit.run()
        cls.t_task.with_user(cls.manager).user_ids = [Command.set([cls.alice.id])]
        cls.env.flush_all()
        cls.env.cr.precommit.run()
        cls.t_bug.with_user(cls.manager).priority = "3"
        cls.env.flush_all()
        cls.env.cr.precommit.run()  # tracked changes are logged just before a commit

    def test_was_finds_past_and_present_values(self):
        review = f'"{self.review.name}"'
        self.assertEqual(self._find(f"status WAS {review}"), self.t_bug, "it left Review again")
        self.assertEqual(self._find(f"status WAS NOT {review}"), self.t_task | self.t_free)
        self.assertEqual(self._find(f"status WAS IN ({review}, Nowhere)".replace(", Nowhere", "")), self.t_bug)
        self.assertIn(self.t_bug, self._find(f'status WAS "{self.todo.name}"'), "the present value counts")
        self.assertEqual(self._find('assignee WAS "Bob Filter"'), self.t_task, "Bob used to hold it")
        self.assertEqual(self._find('assignee WAS "Alice Filter"'), self.t_bug | self.t_task)
        self.assertEqual(self._find("priority WAS Urgent"), self.t_bug)

    def test_changed_with_dates_people_and_values(self):
        self.assertEqual(self._find("status CHANGED"), self.t_bug | self.t_free, "moving into a sprint moves the status too")
        self.assertEqual(self._find("status CHANGED AFTER -7d"), self.t_bug | self.t_free)
        self.assertFalse(self._find("status CHANGED BEFORE -1d"))
        self.assertEqual(self._find("status CHANGED BY Alice".replace("Alice", '"Alice Filter"')), self.t_bug)
        self.assertFalse(self._find("status CHANGED BY me", user=self.bob))
        self.assertEqual(self._find("assignee CHANGED BY me", user=self.manager), self.t_task)
        self.assertEqual(self._find('assignee CHANGED FROM "Bob Filter" TO "Alice Filter"'), self.t_task)
        self.assertFalse(self._find('assignee CHANGED FROM "Alice Filter" TO "Bob Filter"'))
        self.assertEqual(self._find("priority CHANGED TO Urgent AFTER startOfMonth()"), self.t_bug)
        self.assertEqual(self._find(f'status CHANGED FROM Backlog TO "{self.review.name}"'), self.t_bug)

    def test_history_in_words_and_with_other_conditions(self):
        _domain, words = self._tool().compile("status CHANGED BY me AFTER -7d")
        self.assertEqual(words, "Status changed after -7d by you")
        _domain, words = self._tool().compile("assignee WAS NOT \"Bob Filter\"")
        self.assertEqual(words, "Assignee was never Bob Filter")
        self.assertFalse(self._find('assignee CHANGED AND type = Bug'))
        self.assertEqual(self._find('priority CHANGED OR assignee CHANGED'), self.t_bug | self.t_task)
        self.assertEqual(self._find('NOT status CHANGED'), self.t_task)

    def test_history_errors_say_what_to_write(self):
        def message(text):
            with self.assertRaises(QueryError) as caught:
                self._tool().compile(text)
            return caught.exception.message
        self.assertIn("Fields with a history", message("points WAS 3"))
        self.assertIn("only says that it changed", message("due CHANGED FROM today"))
        self.assertIn("can only be written as CHANGED", message("due WAS today"))
        self.assertIn("written twice", message("status CHANGED BY me BY me"))
        self.assertIn("Add a value after AFTER", message("status CHANGED AFTER"))
        self.assertIn("not a date", message("status CHANGED AFTER yesterday"))
        self.assertIn("'unassigned'", message("assignee WAS unassigned"))
        self.assertIsNone(self._tool().to_rows("status CHANGED"), "chip rows cannot show history")

    def test_history_is_offered_by_autocomplete(self):
        def labels(text):
            return [i["label"] for i in self._tool().suggest(text, len(text))["items"]]
        self.assertIn("CHANGED", labels("status "))
        self.assertNotIn("WAS", labels("points "))
        self.assertEqual(labels("status CHANGED ")[:5], ["FROM", "TO", "AFTER", "BEFORE", "BY"])
        self.assertNotIn("AFTER", labels("status CHANGED AFTER -7d "))
        self.assertIn("me", labels("status CHANGED BY "))
        self.assertIn("startOfWeek", labels("status CHANGED AFTER "))
        self.assertIn("AND", labels("status CHANGED BY me "))
