"""Workflow templates (T-1141): copy a workflow to another project, or move it as a file.

A template names everything by words, never by ids, so it works in any project: statuses by name and category,
issue types by name, project fields by name and people by login. What the target project lacks is left out and
reported, and nothing in an existing workflow changes: an import always creates a new workflow.
"""
from odoo import Command, _, api, models
from odoo.exceptions import UserError

from .agile_workflow_editor import MAX_WORKFLOW_STATUSES

TEMPLATE_FORMAT = "agile_workflow"
TEMPLATE_VERSION = 1


class AgileWorkflow(models.Model):
    _inherit = "agile.workflow"

    def agile_template_data(self):
        """This workflow as a plain dict a file can hold."""
        self.ensure_one()
        self._check_workflow_managers(self.project_id)
        statuses = self.status_ids.sorted(lambda s: (s.sequence, s.id))
        names = {status.id: status.stage_id.name for status in statuses}
        moves = []
        for move in self.transition_ids:
            moves.append(dict({
                "name": move.name,
                "from": names[move.from_status_id.id],
                "to": names[move.to_status_id.id],
                "roles": {
                    "contributor": move.allow_contributor, "reviewer": move.allow_reviewer,
                    "manager": move.allow_manager,
                },
                "required_fields": move.required_field_ids.mapped("code"),
                "no_open_subtasks": move.require_no_open_subtasks,
                "not_blocked": move.require_not_blocked,
            }, **move._agile_template_extras()))
        return {
            "format": TEMPLATE_FORMAT,
            "version": TEMPLATE_VERSION,
            "name": self.name,
            "issue_types": self.task_type_ids.mapped("name"),
            "statuses": [{"name": s.stage_id.name, "category": s.category} for s in statuses],
            "moves": moves,
        }

    def agile_copy_to_project(self, project):
        """Copy this workflow into another project; returns the new workflow and what was left out."""
        self.ensure_one()
        return self.agile_create_from_template(project, self.agile_template_data())

    @api.model
    def _template_check(self, data):
        if not isinstance(data, dict) or data.get("format") != TEMPLATE_FORMAT:
            raise UserError(_("This file is not an Agile workflow."))
        if data.get("version") != TEMPLATE_VERSION:
            raise UserError(_("This workflow file has a version this Odoo cannot read."))
        statuses, moves = data.get("statuses"), data.get("moves")
        if not isinstance(statuses, list) or not isinstance(moves, list) or not statuses:
            raise UserError(_("This workflow file has no statuses."))
        if len(statuses) > MAX_WORKFLOW_STATUSES:
            raise UserError(_("A workflow can have %s statuses.", MAX_WORKFLOW_STATUSES))
        category_codes = dict(self.env["project.task.type"]._fields["agile_status"].selection)
        for status in statuses:
            if not isinstance(status, dict) or not str(status.get("name") or "").strip() \
                    or status.get("category") not in category_codes:
                raise UserError(_("A status in this file has no name or a category that does not exist."))

    @api.model
    def agile_create_from_template(self, project, data):
        """Create a new, non-default workflow in ``project``; returns (workflow, notes)."""
        project.ensure_one()
        self._check_workflow_managers(project)
        self._template_check(data)
        notes = []
        taken = set(project.agile_workflow_ids.mapped("name"))
        base = (str(data.get("name") or "").strip() or _("Imported workflow"))[:80]
        name, number = base, 1
        while name in taken:
            number += 1
            name = "%s (%s)" % (base, number)

        workflow = self.create({"name": name, "project_id": project.id})
        # The create hook copies the default workflow; the template replaces it.
        workflow.sudo().transition_ids.unlink()
        workflow.sudo().status_ids.unlink()

        stages = {
            stage.name.casefold(): stage
            for stage in self.env["project.task.type"].with_context(active_test=False).search(
                [("project_ids", "=", project.id)]
            )
        }
        lines = {}
        for position, status in enumerate(data["statuses"]):
            label = status["name"].strip()
            stage = stages.get(label.casefold())
            if not stage:
                stage = self.env["project.task.type"].with_context(active_test=False).create({
                    "name": label, "agile_status": status["category"], "fold": status["category"] == "canceled",
                    "sequence": 1000, "project_ids": [Command.link(project.id)],
                })
                stage._agile_place_in_order(project)
                stages[label.casefold()] = stage
                notes.append(_("Added the status %s to the project.", label))
            if label.casefold() in lines:
                continue
            lines[label.casefold()] = self.env["agile.workflow.status"].sudo().create({
                "workflow_id": workflow.id, "stage_id": stage.id, "sequence": (position + 1) * 10,
            })

        self._template_add_types(workflow, project, data.get("issue_types"), notes)
        self._template_add_moves(workflow, project, lines, data["moves"], notes)
        workflow._queue_workflow_note(workflow, _("Workflow created from a template."))
        return workflow, notes

    @api.model
    def _template_add_types(self, workflow, project, names, notes):
        for label in names if isinstance(names, list) else []:
            task_type = self.env["agile_community.task_type"].search([("name", "=", label)], limit=1)
            if not task_type:
                notes.append(_("The issue type %s does not exist here, so it was left out.", label))
            elif project.agile_workflow_ids.filtered(lambda w: task_type in w.task_type_ids):
                notes.append(_("%s already has a workflow in this project, so it was left out.", label))
            else:
                workflow.task_type_ids = [Command.link(task_type.id)]

    @api.model
    def _template_add_moves(self, workflow, project, lines, moves, notes):
        users = self.env["res.users"]
        seen = set()
        for move in moves:
            source = lines.get(str(move.get("from") or "").casefold())
            target = lines.get(str(move.get("to") or "").casefold())
            title = str(move.get("name") or "").strip()
            if not (source and target and title) or source == target or (source.id, target.id) in seen:
                notes.append(_("The move %s was left out: its statuses are missing or repeated.", title or "?"))
                continue
            seen.add((source.id, target.id))
            roles = move.get("roles") or {}
            values = {
                "name": title, "workflow_id": workflow.id,
                "from_status_id": source.id, "to_status_id": target.id,
                "allow_contributor": bool(roles.get("contributor")),
                "allow_reviewer": bool(roles.get("reviewer")),
                "allow_manager": bool(roles.get("manager", True)),
                "require_no_open_subtasks": bool(move.get("no_open_subtasks")),
                "require_not_blocked": bool(move.get("not_blocked")),
                "required_field_ids": [Command.set(self.env["agile.workflow.field"].search(
                    [("code", "in", move.get("required_fields") or [])]).ids)],
            }
            values.update(self._template_move_extras(move, project, title, notes))
            self.env["agile.workflow.transition"].sudo().create(values)

    @api.model
    def _template_move_extras(self, move, project, title, notes):
        """Values a Pro module adds to an imported move (approvers, required project fields, rules)."""
        return {}

    def action_open_template_wizard(self):
        """Open the share window for this workflow, or for importing into the project the list shows."""
        project = self.project_id or self.env["project.project"].browse(
            self.env.context.get("default_project_id")
        ).exists()
        if not project:
            raise UserError(_("Open the workflows from their project."))
        self._check_workflow_managers(project)
        return {
            "type": "ir.actions.act_window",
            "name": _("Share a workflow"),
            "res_model": "agile_community.workflow_template_wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_workflow_id": self[:1].id or False,
                "default_source_project_id": project.id,
                "default_project_id": project.id,
            },
        }
