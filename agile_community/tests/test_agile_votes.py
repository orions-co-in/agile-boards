from odoo.exceptions import AccessError
from odoo.addons.agile_community.models.agile_query import AgileQuery
from odoo.tests.common import TransactionCase, new_test_user


class TestAgileVotes(TransactionCase):
    """S-1127: one vote per person per issue, shown as a count and usable in queries."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, login="vote_manager", groups="project.group_project_manager")
        cls.project = cls.env["project.project"].with_user(cls.manager).create(
            {"name": "Votes", "agile_enabled": True, "agile_key": "VOT", "agile_method": "kanban"}
        )
        # Created after the team was seeded, so this person is not on the Agile team.
        cls.outsider = new_test_user(cls.env, login="vote_outsider", groups="project.group_project_user")
        cls.member = new_test_user(cls.env, login="vote_member", groups="project.group_project_user")
        cls.env["agile.project.member"].sudo().create(
            {"project_id": cls.project.id, "user_id": cls.member.id, "role": "contributor"}
        )
        cls.issue = cls.env["project.task"].with_user(cls.manager).create({"name": "Popular", "project_id": cls.project.id})
        cls.other = cls.env["project.task"].with_user(cls.manager).create({"name": "Quiet", "project_id": cls.project.id})

    def _issue_as(self, user, issue=None):
        return (issue or self.issue).with_user(user)

    def test_voting_twice_takes_the_vote_back(self):
        issue = self._issue_as(self.manager)
        issue.agile_toggle_vote()
        self.assertEqual((issue.agile_vote_count, issue.agile_has_voted), (1, True))
        issue.agile_toggle_vote()
        self.assertEqual((issue.agile_vote_count, issue.agile_has_voted), (0, False))

    def test_each_person_counts_once(self):
        self._issue_as(self.manager).agile_toggle_vote()
        self._issue_as(self.member).agile_toggle_vote()
        self.assertEqual(self.issue.agile_vote_count, 2)
        self.assertFalse(self._issue_as(self.outsider).agile_has_voted)

    def test_a_person_outside_the_team_cannot_vote(self):
        with self.assertRaises(AccessError):
            self._issue_as(self.outsider).agile_toggle_vote()
        self.assertEqual(self.issue.agile_vote_count, 0)

    def test_votes_cannot_be_written_directly(self):
        with self.assertRaises(AccessError):
            self.env["agile.issue.vote"].with_user(self.manager).create({"task_id": self.issue.id, "user_id": self.manager.id})

    def test_two_vote_rows_for_one_person_are_refused(self):
        Vote = self.env["agile.issue.vote"].sudo()
        Vote.create({"task_id": self.issue.id, "user_id": self.manager.id})
        with self.assertRaises(Exception), self.cr.savepoint():
            Vote.create({"task_id": self.issue.id, "user_id": self.manager.id})

    def test_the_query_language_filters_and_sorts_by_votes(self):
        self._issue_as(self.manager).agile_toggle_vote()
        self._issue_as(self.member).agile_toggle_vote()
        self._issue_as(self.manager, self.other).agile_toggle_vote()
        query = AgileQuery(self.env(user=self.manager), self.project)
        tasks = self.env["project.task"].with_user(self.manager)
        domain, _words = query.compile("votes >= 2")
        self.assertEqual(tasks.search(domain), self.issue)
        ordered = tasks.search([("project_id", "=", self.project.id)], order=query.order("ORDER BY votes DESC"))
        self.assertEqual(ordered[:2], self.issue | self.other)
        self.assertEqual(ordered[0], self.issue)

    def test_votes_on_a_restricted_issue_are_hidden_from_other_people(self):
        self._issue_as(self.manager).agile_toggle_vote()
        self.issue.write({"agile_restricted": True})
        votes = self.env["agile.issue.vote"].with_user(self.member).search([("task_id", "=", self.issue.id)])
        self.assertFalse(votes)
