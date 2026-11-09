from odoo import api, models
from odoo.fields import Domain

AGILE_SCOPED_MODELS = ("project.task", "project.sprint", "project.version")


class ProjectProject(models.Model):
    _inherit = "project.project"

    @api.model
    def _agile_hidden_documents(self):
        """Agile documents the current user may not read, as {model: ids}.

        A document is hidden when its project is not open to the user in Odoo Project,
        when the user has no Agile role in it, or when the document itself is closed to them.
        Messages, activities, followers and attachments of such documents are hidden too.
        """
        user = self.env.user
        # access checks read the database, so pending changes (members, privacy) must be written first
        self.env.flush_all()
        projects = self.sudo().with_context(active_test=False).search([("agile_enabled", "=", True)])
        hidden = {}
        if not projects:
            return hidden
        blocked = projects.filtered(
            lambda project: project._agile_role_for_user(user) == "none"
            or not project.with_user(user).has_access("read")
        )
        open_projects = projects - blocked
        for model_name in AGILE_SCOPED_MODELS:
            if model_name not in self.env:
                continue
            documents = self.env[model_name].sudo().with_context(active_test=False)
            extra = [("agile_issue", "=", True)] if model_name == "project.task" else []
            ids = set(documents.search(extra + [("project_id", "in", blocked.ids)]).ids)
            if open_projects:
                scope = extra + [("project_id", "in", open_projects.ids)]
                everything = set(documents.search(scope).ids)
                readable = set(documents.with_user(user).search(scope).ids)
                ids |= everything - readable
            if ids:
                hidden[model_name] = ids
        return hidden


class AgileScopedAccessMixin(models.AbstractModel):
    """Keeps the chatter of an Agile document as private as the document (Odoo 20 reads access from the domain)."""

    _name = "agile.scoped.access.mixin"
    _description = "Agile document-scoped access"
    _agile_model_field = "res_model"
    _agile_id_field = "res_id"
    _agile_parent_field = None  # a reply points at its document only through its parent

    def _access_domain(self, operation):
        domain = super()._access_domain(operation)
        if operation != "read" or self.env.su or domain.is_false():
            return domain
        for model_name, ids in self.env["project.project"]._agile_hidden_documents().items():
            hidden = Domain(self._agile_model_field, "=", model_name) & Domain(self._agile_id_field, "in", sorted(ids))
            prefix = ""
            if self._agile_parent_field:
                for _depth in range(3):
                    prefix += self._agile_parent_field + "."
                    hidden |= Domain(prefix + self._agile_model_field, "=", model_name) & Domain(
                        prefix + self._agile_id_field, "in", sorted(ids)
                    )
            domain &= ~hidden
        return domain
