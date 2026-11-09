from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


class AgileIssueLink(models.Model):
    _name = "agile_community.issue_link"
    _description = "Agile Issue Relationship"
    _order = "id"

    issue_a_id = fields.Many2one(
        "project.task", required=True, index=True, ondelete="cascade"
    )
    issue_b_id = fields.Many2one(
        "project.task", required=True, index=True, ondelete="cascade"
    )
    link_type = fields.Selection(
        [
            ("relates", "Relates to"),
            ("duplicates", "Duplicates"),
            ("clones", "Clones"),
        ],
        required=True,
        index=True,
    )
    # The side that "clones" or "duplicates" the other. Empty for "relates" and for
    # duplicate rows made before links had a direction (shown with neutral wording).
    source_id = fields.Many2one("project.task", index=True, ondelete="cascade")

    _unique_link = models.Constraint(
        "unique (issue_a_id, issue_b_id, link_type)",
        "This relationship already exists.",
    )
    _source_in_link = models.Constraint(
        "CHECK (source_id IS NULL OR source_id = issue_a_id OR source_id = issue_b_id)",
        "The source of a link must be one of its two issues.",
    )
    _ordered_link = models.Constraint(
        "CHECK (issue_a_id < issue_b_id)",
        "Issue relationships must use a stable issue order.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise AccessError(_("Use the issue form to manage relationships."))
        normalized = []
        for values in vals_list:
            values = dict(values)
            issue_a = self.env["project.task"].browse(values.get("issue_a_id"))
            issue_b = self.env["project.task"].browse(values.get("issue_b_id"))
            if not issue_a or not issue_b or issue_a == issue_b:
                raise ValidationError(_("An issue cannot be linked to itself."))
            if issue_a.id > issue_b.id:
                values["issue_a_id"], values["issue_b_id"] = issue_b.id, issue_a.id
                issue_a, issue_b = issue_b, issue_a
            if not issue_a.agile_issue or not issue_b.agile_issue:
                raise ValidationError(
                    _("Only Agile issues can be linked to other Agile issues.")
                )
            if issue_a.company_id != issue_b.company_id:
                raise ValidationError(
                    _("Issues in different companies cannot be linked.")
                )
            source = values.get("source_id")
            if source and (
                values.get("link_type") == "relates" or source not in (issue_a.id, issue_b.id)
            ):
                raise ValidationError(_("The source of a link must be one of its two issues."))
            normalized.append(values)
        links = super().create(normalized)
        (links.issue_a_id | links.issue_b_id).invalidate_recordset(
            ["agile_related_issue_ids", "agile_duplicate_issue_ids"]
        )
        return links

    def write(self, values):
        if not self.env.su:
            raise AccessError(_("Use the issue form to manage relationships."))
        if {"issue_a_id", "issue_b_id"} & values.keys():
            raise ValidationError(_("Existing issue links cannot be retargeted."))
        return super().write(values)

    def unlink(self):
        if not self.env.su:
            raise AccessError(_("Use the issue form to manage relationships."))
        tasks = self.issue_a_id | self.issue_b_id
        result = super().unlink()
        tasks.invalidate_recordset(
            ["agile_related_issue_ids", "agile_duplicate_issue_ids"]
        )
        return result
