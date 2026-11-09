from odoo import _, api, fields, models


class AgileCloneWizard(models.TransientModel):
    _name = "agile_community.clone_wizard"
    _description = "Clone an Agile issue"

    task_id = fields.Many2one("project.task", required=True, ondelete="cascade")
    name = fields.Char(string="Title", required=True)
    copy_subtasks = fields.Boolean(string="Copy sub-tasks", default=True)
    copy_attachments = fields.Boolean(string="Copy attachments")
    same_sprint = fields.Boolean(string="Add to the same sprint")
    sprint_can_join = fields.Boolean(compute="_compute_sprint_can_join")
    has_sprint = fields.Boolean(compute="_compute_notes")
    subtask_note = fields.Char(compute="_compute_notes")
    attachment_note = fields.Char(compute="_compute_notes")
    sprint_note = fields.Char(compute="_compute_notes")

    @api.depends("task_id", "task_id.child_ids", "task_id.sprint_id.state")
    def _compute_notes(self):
        Attachment = self.env["ir.attachment"]
        for wizard in self:
            task = wizard.task_id
            wizard.has_sprint = bool(task.sprint_id)
            count = len(task.child_ids.filtered(lambda child: child.agile_issue and child.has_access("read")))
            wizard.subtask_note = (
                _("%s sub-task, copied as an open issue.", count) if count == 1
                else _("%s sub-tasks, copied as open issues.", count) if count
                else _("This issue has no sub-tasks.")
            )
            files = Attachment.search([("res_model", "=", "project.task"), ("res_id", "=", task.id)])
            size = sum(files.mapped("file_size"))
            wizard.attachment_note = (
                _("%(count)s files, %(size).1f MB.", count=len(files), size=size / 1024 / 1024)
                if len(files) != 1
                else _("1 file, %.1f MB.", size / 1024 / 1024)
            ) if files else _("This issue has no attachments.")
            if task.sprint_id.state == "draft":
                wizard.sprint_note = _("Off by default. The clone joins %s.", task.sprint_id.name)
            elif task.sprint_id:
                wizard.sprint_note = _(
                    "Off by default. Unavailable because %s is active; the clone starts in the Backlog.",
                    task.sprint_id.name,
                )
            else:
                wizard.sprint_note = ""

    @api.depends_context("uid")
    @api.depends("task_id.sprint_id.state")
    def _compute_sprint_can_join(self):
        # A running sprint keeps its commitment, and joining a sprint follows the permission scheme.
        for wizard in self:
            task = wizard.task_id
            wizard.sprint_can_join = task.sprint_id.state == "draft" and task.project_id._agile_allows(
                "sprint_membership"
            )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") and vals.get("task_id"):
                task = self.env["project.task"].browse(vals["task_id"])
                vals["name"] = _("Clone of %s", task.name)
        return super().create(vals_list)

    def action_clone(self):
        self.ensure_one()
        result = self.task_id.agile_clone(
            title=self.name,
            copy_subtasks=self.copy_subtasks,
            copy_attachments=self.copy_attachments,
            same_sprint=self.same_sprint,
        )
        return {
            "type": "ir.actions.act_window",
            "res_model": "project.task",
            "res_id": result["id"],
            "view_mode": "form",
            "target": "current",
        }
