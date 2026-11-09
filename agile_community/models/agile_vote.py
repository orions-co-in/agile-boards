"""Votes on issues (S-1127): one vote per person per issue, a light signal of interest."""
from odoo import _, api, fields, models
from odoo.exceptions import AccessError


class AgileIssueVote(models.Model):
    _name = "agile.issue.vote"
    _description = "Agile Issue Vote"
    _order = "id"

    task_id = fields.Many2one("project.task", required=True, index=True, ondelete="cascade")
    user_id = fields.Many2one("res.users", required=True, index=True, ondelete="cascade")

    _one_vote_each = models.Constraint("unique (task_id, user_id)", "A person votes once for an issue.")

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise AccessError(_("Votes are added with the Vote button."))
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError(_("A vote cannot be edited."))

    def unlink(self):
        if not self.env.su and not self.env.context.get("module_uninstall"):
            raise AccessError(_("Votes are removed with the Vote button."))
        return super().unlink()


class ProjectTask(models.Model):
    _inherit = "project.task"

    agile_vote_ids = fields.One2many("agile.issue.vote", "task_id", string="Votes", copy=False)
    agile_vote_count = fields.Integer(string="Votes", compute="_compute_agile_vote_count", store=True)
    agile_has_voted = fields.Boolean(string="You voted", compute="_compute_agile_has_voted")

    @api.depends("agile_vote_ids")
    def _compute_agile_vote_count(self):
        for task in self:
            task.agile_vote_count = len(task.sudo().agile_vote_ids)

    @api.depends_context("uid")
    @api.depends("agile_vote_ids.user_id")
    def _compute_agile_has_voted(self):
        for task in self:
            task.agile_has_voted = self.env.user in task.sudo().agile_vote_ids.user_id

    def agile_toggle_vote(self):
        """Add this person's vote, or take it back when they already voted (the form reloads after the click)."""
        self.ensure_one()
        self.check_access("read")
        if not self.agile_issue or self.project_id._agile_role_for_user() == "none":
            raise AccessError(_("Only people on the project's Agile team can vote."))
        vote = self.sudo().agile_vote_ids.filtered(lambda v: v.user_id == self.env.user)
        if vote:
            vote.sudo().unlink()
        else:
            self.env["agile.issue.vote"].sudo().create({"task_id": self.id, "user_id": self.env.user.id})
        self.invalidate_recordset(["agile_vote_ids", "agile_vote_count", "agile_has_voted"])
        return True
