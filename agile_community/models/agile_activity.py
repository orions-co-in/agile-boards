from odoo import api, models, _
from odoo.exceptions import AccessError, ValidationError


AGILE_ACTIVITY_ROLES = ("manager", "contributor", "reviewer")


class ProjectTask(models.Model):
    _inherit = "project.task"

    def _check_agile_follower_mutation(self):
        if self.env.su:
            return
        tasks = self.sudo().filtered(
            lambda task: task.agile_issue and task.project_id.agile_enabled
        ).with_user(self.env.user)
        if tasks:
            tasks._check_agile_stakeholder_mutation()

    def message_post(self, **kwargs):
        """A person who cannot read an Agile issue is not notified about it, however they are mentioned (E2E-007).

        The notification would carry the issue's title and the comment text to someone the record rules keep out.
        """
        partner_ids = kwargs.get("partner_ids")
        if partner_ids and len(self) == 1 and self.sudo().agile_issue:
            task = self.sudo()
            users = self.env["res.users"].sudo().with_context(active_test=False).search(
                [("partner_id", "in", partner_ids)]
            )
            readable = {
                user.partner_id.id for user in users if task.with_user(user).has_access("read")
            }
            kwargs["partner_ids"] = [pid for pid in partner_ids if pid in readable]
        return super().message_post(**kwargs)

    def message_subscribe(self, partner_ids=None, subtype_ids=None):
        current_partner_id = self.env.user.partner_id.id
        if partner_ids and set(partner_ids) != {current_partner_id}:
            self._check_agile_follower_mutation()
        return super().message_subscribe(
            partner_ids=partner_ids, subtype_ids=subtype_ids
        )

    def message_unsubscribe(self, partner_ids=None):
        current_partner_id = self.env.user.partner_id.id
        if partner_ids and set(partner_ids) != {current_partner_id}:
            self._check_agile_follower_mutation()
        return super().message_unsubscribe(partner_ids=partner_ids)


class MailActivity(models.Model):
    _inherit = "mail.activity"

    @api.model_create_multi
    def create(self, vals_list):
        defaults = self.default_get(["res_model_id", "res_id", "user_id"])
        guard_values = []
        for values in vals_list:
            resolved = dict(values)
            for field_name in ("res_model_id", "res_id", "user_id"):
                if field_name not in resolved and defaults.get(field_name):
                    resolved[field_name] = defaults[field_name]
            guard_values.append(resolved)
        self._check_agile_activity_mutation(values_list=guard_values)
        return super().create(vals_list)

    def write(self, vals):
        self._check_agile_activity_mutation(values_list=[vals])
        return super().write(vals)

    def unlink(self):
        self._check_agile_activity_mutation()
        return super().unlink()

    def _agile_activity_links(self, activities=None, values_list=None):
        links = set()
        activities = activities or self
        values_list = values_list or []
        for activity in activities:
            if activity.res_model and activity.res_id:
                links.add((activity.res_model, activity.res_id))
            for values in values_list:
                model_name = values.get("res_model")
                model_id = values.get(
                    "res_model_id", activity.res_model_id.id
                )
                if model_name is None and model_id:
                    model_name = self.env["ir.model"].sudo().browse(
                        model_id
                    ).model
                record_id = values.get("res_id", activity.res_id)
                if model_name and record_id:
                    links.add((model_name, record_id))
        for values in values_list:
            model_name = values.get("res_model")
            model_id = values.get("res_model_id")
            if model_name is None and model_id:
                model_name = self.env["ir.model"].sudo().browse(model_id).model
            record_id = values.get("res_id")
            if model_name and record_id:
                links.add((model_name, record_id))
        agile_documents = []
        for model_name, record_id in links:
            if model_name not in ("project.task", "project.sprint", "project.version"):
                continue
            document = self.env[model_name].sudo().browse(record_id).exists()
            if not document:
                continue
            if model_name == "project.task":
                document = document.filtered(
                    lambda task: task.agile_issue and task.project_id.agile_enabled
                )
            else:
                document = document.filtered(
                    lambda record: record.project_id.agile_enabled
                )
            if document:
                agile_documents.append((model_name, document))
        return agile_documents

    def _check_agile_activity_mutation(self, values_list=None):
        if self.env.su:
            return
        documents = self._agile_activity_links(values_list=values_list)
        for activity in self:
            documents.extend(
                self._agile_activity_links(
                    activities=activity,
                    values_list=values_list,
                )
            )
        for model_name, records in documents:
            for record in records:
                project = record.project_id
                if not project.with_user(self.env.user).has_access("read"):
                    raise AccessError(
                        _("You must retain native Odoo Project access to manage activities here.")
                    )
                if project._agile_role_for_user(self.env.user) not in AGILE_ACTIVITY_ROLES:
                    raise AccessError(
                        _("Only Agile managers, contributors, and reviewers can manage project activities.")
                    )

                assigned_ids = set()
                if self:
                    for activity in self:
                        updates = (values_list or [{}])[0]
                        assigned_ids.add(
                            updates.get("user_id", activity.user_id.id)
                        )
                else:
                    defaults = self.default_get(["user_id"])
                    for values in values_list or [{}]:
                        assigned_ids.add(
                            values.get("user_id", defaults.get("user_id"))
                            or self.env.uid
                        )
                for user_id in filter(None, assigned_ids):
                    assignee = self.env["res.users"].sudo().browse(user_id).exists()
                    if (
                        not assignee
                        or not assignee.active
                        or assignee.share
                        or project._agile_role_for_user(assignee) == "none"
                    ):
                        raise ValidationError(
                            _("Assign Agile activities only to active internal members of this project.")
                        )

    def _agile_activity_read_allowed(self, activity):
        for model_name, records in self._agile_activity_links(activities=activity):
            for record in records:
                project = record.project_id
                if project._agile_role_for_user(self.env.user) == "none":
                    return False
                if not project.with_user(self.env.user).has_access("read"):
                    return False
                if model_name == "project.task":
                    if not record.with_user(self.env.user).has_access("read"):
                        return False
                elif not record.with_user(self.env.user).has_access("read"):
                    return False
        return True

    def _check_access(self, operation):
        result = super()._check_access(operation)
        if operation != "read" or self.env.su or not self:
            return result
        readable = self - result[0] if result else self
        forbidden = readable.filtered(
            lambda activity: not self._agile_activity_read_allowed(activity)
        )
        if not forbidden:
            return result
        if result:
            return result[0] | forbidden, result[1]
        return forbidden, lambda: forbidden._make_access_error(operation)

    @api.model
    def _search(
        self,
        domain,
        offset=0,
        limit=None,
        order=None,
        *,
        bypass_access=False,
        **kwargs,
    ):
        query = super()._search(
            domain,
            offset=offset,
            limit=limit,
            order=order,
            bypass_access=bypass_access,
            **kwargs,
        )
        if self.env.su or bypass_access:
            return query
        activity_ids = [
            row[0]
            for row in self.env.execute_query(
                query.select(self._field_to_sql(self._table, "id"))
            )
        ]
        readable = self.browse(activity_ids)._filtered_access("read")
        return readable._as_query(order)


class MailFollowers(models.Model):
    _inherit = "mail.followers"

    def _agile_follower_links(self, values_list=None):
        links = set()
        values_list = values_list or []
        defaults = self.default_get(["res_model", "res_id", "partner_id"])
        for follower in self.sudo():
            if follower.res_model and follower.res_id:
                links.add((
                    follower.res_model,
                    follower.res_id,
                    follower.partner_id.id,
                ))

        records = list(self) if self else [None]
        for values in values_list:
            for follower in records:
                model_name = values.get(
                    "res_model", follower.res_model if follower else defaults.get("res_model")
                )
                record_id = values.get(
                    "res_id", follower.res_id if follower else defaults.get("res_id")
                )
                partner_id = values.get(
                    "partner_id",
                    follower.partner_id.id if follower else defaults.get("partner_id"),
                )
                if model_name and record_id:
                    links.add((model_name, record_id, partner_id))
        return links

    def _check_agile_follower_mutation(self, values_list=None):
        if self.env.su:
            return
        for model_name, record_id, partner_id in self._agile_follower_links(
            values_list=values_list
        ):
            if model_name not in (
                "project.task", "project.sprint", "project.version"
            ):
                continue
            document = self.env[model_name].sudo().browse(record_id).exists()
            if not document:
                continue
            if model_name == "project.task":
                document = document.filtered(
                    lambda task: task.agile_issue and task.project_id.agile_enabled
                )
            else:
                document = document.filtered(
                    lambda record: record.project_id.agile_enabled
                )
            for record in document:
                project = record.project_id
                role = project._agile_role_for_user(self.env.user)
                if (
                    not project.with_user(self.env.user).has_access("read")
                    or not record.with_user(self.env.user).has_access("read")
                    or role == "none"
                ):
                    raise AccessError(
                        _("You must retain Agile team and Project access to change followers here.")
                    )
                if (
                    partner_id != self.env.user.partner_id.id
                    and role not in AGILE_ACTIVITY_ROLES
                ):
                    raise AccessError(
                        _("Only Agile managers, contributors, and reviewers can change other followers.")
                    )

    def _agile_follower_documents(self, followers):
        linked_records = []
        for follower in followers.sudo():
            if follower.res_model not in (
                "project.task", "project.sprint", "project.version"
            ) or not follower.res_id:
                continue
            document = self.env[follower.res_model].sudo().browse(
                follower.res_id
            ).exists()
            if not document:
                continue
            if follower.res_model == "project.task":
                document = document.filtered(
                    lambda task: task.agile_issue and task.project_id.agile_enabled
                )
            else:
                document = document.filtered(
                    lambda record: record.project_id.agile_enabled
                )
            if document:
                linked_records.append((follower, follower.res_model, document))
        return linked_records

    def _agile_follower_read_allowed(self, follower, model_name, document):
        project = document.project_id
        if project._agile_role_for_user(self.env.user) == "none":
            return False
        if model_name == "project.task":
            return document.with_user(self.env.user).has_access("read")
        return (
            project.with_user(self.env.user).has_access("read")
            and document.with_user(self.env.user).has_access("read")
        )

    def _check_access(self, operation):
        result = super()._check_access(operation)
        if operation != "read" or self.env.su or not self:
            return result
        readable = self - result[0] if result else self
        forbidden = self.browse()
        for follower, model_name, document in self._agile_follower_documents(readable):
            if not self._agile_follower_read_allowed(
                follower, model_name, document
            ):
                forbidden |= follower
        if not forbidden:
            return result
        if result:
            return result[0] | forbidden, result[1]
        return forbidden, lambda: forbidden._make_access_error(operation)

    @api.model
    def _search(
        self,
        domain,
        offset=0,
        limit=None,
        order=None,
        *,
        bypass_access=False,
        **kwargs,
    ):
        query = super()._search(
            domain,
            offset=offset,
            limit=limit,
            order=order,
            bypass_access=bypass_access,
            **kwargs,
        )
        if self.env.su or bypass_access:
            return query
        follower_ids = [
            row[0]
            for row in self.env.execute_query(
                query.select(self._field_to_sql(self._table, "id"))
            )
        ]
        readable = self.browse(follower_ids)._filtered_access("read")
        return readable._as_query(order)

    @api.model_create_multi
    def create(self, vals_list):
        defaults = self.default_get(["res_model_id", "res_id", "user_id"])
        guard_values = []
        for values in vals_list:
            resolved = dict(values)
            for field_name in ("res_model_id", "res_id", "user_id"):
                if field_name not in resolved and defaults.get(field_name):
                    resolved[field_name] = defaults[field_name]
            guard_values.append(resolved)
        self._check_agile_follower_mutation(values_list=guard_values)
        return super().create(vals_list)

    def write(self, vals):
        self._check_agile_follower_mutation(values_list=[vals])
        return super().write(vals)

    def unlink(self):
        self._check_agile_follower_mutation()
        return super().unlink()
