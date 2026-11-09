from datetime import datetime, time, timedelta
from types import SimpleNamespace

import pytz
from dateutil.relativedelta import relativedelta

from odoo import Command, fields
from odoo.tests.common import (
    HttpCase,
    JsonRpcException,
    TransactionCase,
    new_test_user,
    tagged,
)
from odoo.tools.safe_eval import safe_eval


class TestAgileMyWork(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(
            cls.env,
            login="my_work_manager",
            groups="project.group_project_manager",
        )
        cls.contributor = new_test_user(
            cls.env,
            login="my_work_contributor",
            groups="project.group_project_user",
        )
        cls.reviewer = new_test_user(
            cls.env,
            login="my_work_reviewer",
            groups="agile_community.group_agile_reviewer",
        )
        cls.project = cls.env["project.project"].create({
            "name": "My Work",
            "privacy_visibility": "employees",
            "user_id": cls.manager.id,
            "agile_enabled": True,
            "agile_key": "MYWORK",
            "agile_method": "kanban",
        })
        cls.stages = {
            stage.agile_status: stage
            for stage in cls.project.type_ids.filtered("agile_status")
        }

    def test_a_mention_does_not_notify_a_person_who_cannot_read_the_issue(self):
        """E2E-007: the notification would carry the title and the comment to someone the record rules keep out."""
        private = self.env["project.project"].with_user(self.manager).create({
            "name": "Private mentions", "privacy_visibility": "followers", "agile_enabled": True,
            "agile_key": "PRVM", "agile_method": "kanban",
        })
        self.env["agile.project.member"].sudo().search([
            ("project_id", "=", private.id), ("user_id", "=", self.contributor.id)]).unlink()
        task = self.env["project.task"].with_user(self.manager).create({"name": "Secret plan", "project_id": private.id})
        self.assertFalse(task.with_user(self.contributor).has_access("read"))
        message = task.with_user(self.manager).message_post(
            body="Confidential words", message_type="comment", subtype_xmlid="mail.mt_comment",
            partner_ids=[self.contributor.partner_id.id, self.manager.partner_id.id],
        )
        told = self.env["mail.notification"].sudo().search([("mail_message_id", "=", message.id)]).res_partner_id
        self.assertNotIn(self.contributor.partner_id, told)
        self.assertNotIn(self.contributor.partner_id, message.sudo().partner_ids)

    def _new_issue(self, name, user=None, status="backlog", deadline=None):
        task = self.env["project.task"].with_user(self.manager).create({
            "name": name,
            "project_id": self.project.id,
            "description": "Enough detail for workflow actions.",
            "user_ids": [Command.set(user.ids)] if user else [Command.clear()],
            "date_deadline": deadline,
        })
        lifecycle = {
            "backlog": [],
            "review": ["ready", "progress", "review"],
            "done": ["ready", "progress", "review", "done"],
        }
        for next_status in lifecycle[status]:
            task.with_user(self.manager)._agile_transition(next_status)
        return task

    def _action_tasks(self, xmlid, user, timezone="UTC"):
        action = self.env.ref(xmlid)
        task_model = self.env["project.task"].with_user(user).with_context(
            tz=timezone,
            allowed_company_ids=[self.env.company.id],
        )
        eval_context = {"uid": user.id}
        if xmlid.endswith("action_agile_my_work_due_soon"):
            client_timezone = pytz.timezone(timezone)

            class ClientDateTime(datetime):
                def to_utc(self):
                    return client_timezone.localize(self).astimezone(
                        pytz.UTC
                    ).replace(tzinfo=None)

            eval_context.update({
                "context_today": lambda: fields.Date.context_today(task_model),
                "relativedelta": relativedelta,
                "datetime": SimpleNamespace(
                    datetime=ClientDateTime,
                    time=time,
                ),
            })
        domain = safe_eval(action.domain, eval_context)
        return task_model.search(domain)

    def test_assigned_blocked_review_and_due_soon_lists(self):
        today = fields.Date.context_today(
            self.env["project.task"].with_context(tz="Asia/Kolkata")
        )

        def deadline_on(day_offset, due_time=time(hour=12)):
            due_date = today + timedelta(days=day_offset)
            local_deadline = pytz.timezone("Asia/Kolkata").localize(
                datetime.combine(due_date, due_time)
            )
            return local_deadline.astimezone(pytz.UTC).replace(tzinfo=None)

        assigned = self._new_issue("Assigned", self.contributor)
        blocked = self._new_issue("Blocked", self.contributor)
        blocked.write({
            "agile_blocked": True,
            "agile_block_reason": "Waiting for a dependency.",
        })
        due_today = self._new_issue(
            "Due today", self.contributor, deadline=deadline_on(0)
        )
        due_seven_days = self._new_issue(
            "Due in seven days", self.contributor, deadline=deadline_on(7)
        )
        near_timezone_boundary = self._new_issue(
            "Due near timezone boundary",
            self.contributor,
            deadline=deadline_on(7, time(hour=23, minute=30)),
        )
        outside_window = self._new_issue(
            "Due later", self.contributor, deadline=deadline_on(8)
        )
        utc_today = fields.Date.context_today(
            self.env["project.task"].with_context(tz="UTC")
        )
        utc_only = False
        if today > utc_today:
            utc_only = self._new_issue(
                "Due today only in UTC",
                self.contributor,
                deadline=datetime.combine(utc_today, time(minute=30)),
            )
        overdue = self._new_issue(
            "Overdue", self.contributor, deadline=deadline_on(-1)
        )
        completed = self._new_issue(
            "Completed", self.contributor, status="done",
            deadline=deadline_on(2),
        )
        review = self._new_issue(
            "Review request", self.reviewer, status="review"
        )
        native = self.env["project.project"].create({"name": "Native"})
        native_task = self.env["project.task"].create({
            "name": "Native task",
            "project_id": native.id,
            "user_ids": [Command.set(self.contributor.ids)],
        })

        assigned_ids = set(self._action_tasks(
            "agile_community.action_agile_my_work_assigned",
            self.contributor,
        ).ids)
        self.assertIn(assigned.id, assigned_ids)
        self.assertNotIn(native_task.id, assigned_ids)

        blocked_ids = set(self._action_tasks(
            "agile_community.action_agile_my_work_blocked",
            self.contributor,
        ).ids)
        self.assertEqual(blocked_ids, {blocked.id})

        review_ids = set(self._action_tasks(
            "agile_community.action_agile_my_work_review",
            self.reviewer,
        ).ids)
        self.assertEqual(review_ids, {review.id})

        due_ids = set(self._action_tasks(
            "agile_community.action_agile_my_work_due_soon",
            self.contributor,
            timezone="Asia/Kolkata",
        ).ids)
        self.assertEqual(
            due_ids,
            {due_today.id, due_seven_days.id, near_timezone_boundary.id},
        )
        utc_due_ids = set(self._action_tasks(
            "agile_community.action_agile_my_work_due_soon",
            self.contributor,
            timezone="UTC",
        ).ids)
        self.assertIn(near_timezone_boundary.id, due_ids)
        self.assertFalse({outside_window.id, overdue.id, completed.id} & due_ids)
        if utc_only:
            self.assertIn(utc_only.id, utc_due_ids)
            self.assertNotIn(utc_only.id, due_ids)
        search_arch = self.env.ref(
            "agile_community.project_task_search_agile_my_work"
        ).arch_db
        self.assertIn("context_today()", search_arch)
        self.assertIn("relativedelta(days=8)", search_arch)
        self.assertIn(".to_utc()", search_arch)

    def test_reassignment_moves_issue_between_personal_lists(self):
        task = self._new_issue("Reassigned issue", self.contributor)
        task_ids_for_contributor = set(self._action_tasks(
            "agile_community.action_agile_my_work_assigned",
            self.contributor,
        ).ids)
        self.assertIn(task.id, task_ids_for_contributor)

        task.with_user(self.manager).write({
            "user_ids": [Command.set(self.reviewer.ids)],
        })
        task_ids_for_contributor = set(self._action_tasks(
            "agile_community.action_agile_my_work_assigned",
            self.contributor,
        ).ids)
        task_ids_for_reviewer = set(self._action_tasks(
            "agile_community.action_agile_my_work_assigned",
            self.reviewer,
        ).ids)
        self.assertNotIn(task.id, task_ids_for_contributor)
        self.assertIn(task.id, task_ids_for_reviewer)

    def test_assignment_uses_native_project_notification(self):
        task = self._new_issue("Assignment notice")
        task.with_user(self.manager).write({
            "user_ids": [Command.set(self.contributor.ids)],
        })
        self.env.flush_all()
        self.env.cr.precommit.run()
        notifications = self.env["mail.notification"].search([
            ("res_partner_id", "=", self.contributor.partner_id.id),
            ("mail_message_id.model", "=", "project.task"),
            ("mail_message_id.res_id", "=", task.id),
        ])
        self.assertTrue(
            any("assigned" in (notification.mail_message_id.subject or "").lower()
                for notification in notifications)
        )

    def test_inactive_assignee_does_not_remain_in_active_user_queue(self):
        inactive_user = new_test_user(
            self.env,
            login="my_work_inactive_assignee",
            groups="project.group_project_user",
        )
        task = self._new_issue("Inactive assignee", self.contributor)
        inactive_user.write({"active": False})
        task.with_user(self.manager).write({
            "user_ids": [Command.set(inactive_user.ids)],
        })
        contributor_ids = set(self._action_tasks(
            "agile_community.action_agile_my_work_assigned",
            self.contributor,
        ).ids)
        self.assertNotIn(task.id, contributor_ids)

    def test_review_queue_menu_requires_reviewer_or_manager_group(self):
        menu = self.env.ref("agile_community.menu_agile_my_work_review")
        self.assertIn(
            self.env.ref("agile_community.group_agile_reviewer"),
            menu.group_ids,
        )
        self.assertIn(
            self.env.ref("project.group_project_manager"),
            menu.group_ids,
        )
        self.assertFalse(self.contributor.group_ids & menu.group_ids)


@tagged("post_install", "-at_install")
class TestAgileMyWorkActionAccess(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.contributor = new_test_user(
            cls.env,
            login="my_work_http_contributor",
            groups="base.group_user,project.group_project_user",
        )
        cls.reviewer = new_test_user(
            cls.env,
            login="my_work_http_reviewer",
            groups="base.group_user,agile_community.group_agile_reviewer",
        )
        cls.manager = new_test_user(
            cls.env,
            login="my_work_http_manager",
            groups="base.group_user,project.group_project_manager",
        )
        cls.project = cls.env["project.project"].create({
            "name": "My Work HTTP access",
            "privacy_visibility": "employees",
            "user_id": cls.manager.id,
            "agile_enabled": True,
            "agile_key": "MYWORKHTTP",
            "agile_method": "kanban",
        })
    def _load_review_queue(self, user):
        self.authenticate(user.login, user.login)
        return self.make_jsonrpc_request(
            "/web/action/load", {"action_id": "agile-review-requested"}
        )

    def test_review_queue_action_is_server_restricted(self):
        with self.assertRaises(JsonRpcException):
            self._load_review_queue(self.contributor)

        for user in (self.reviewer, self.manager):
            action = self._load_review_queue(user)
            self.assertEqual(action["name"], "Review requested")

    def test_my_work_actions_preserve_project_record_rules(self):
        hidden_project = self.env["project.project"].create({
            "name": "Hidden Agile project",
            "privacy_visibility": "invited_users",
            "user_id": self.manager.id,
            "agile_enabled": True,
            "agile_key": "HIDDEN",
            "agile_method": "kanban",
        })
        hidden_issue = self.env["project.task"].with_user(self.manager).create({
            "name": "Hidden assigned issue",
            "description": "Request review without exposing this private task.",
            "project_id": hidden_project.id,
            "user_ids": [Command.set(self.manager.ids)],
        })
        hidden_issue.with_user(self.manager)._agile_transition("ready")
        hidden_issue.with_user(self.manager)._agile_transition("progress")
        hidden_issue.with_user(self.manager)._agile_transition("review")
        results = self.env["project.task"].with_user(
            self.reviewer
        ).with_context(allowed_company_ids=[self.env.company.id]).search(
            safe_eval(
                self.env.ref("agile_community.action_agile_my_work_review").domain,
                {"uid": self.reviewer.id},
            )
        )
        self.assertNotIn(hidden_issue.id, results.ids)
