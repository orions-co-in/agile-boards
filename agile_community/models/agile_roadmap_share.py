"""Shared roadmap views (U-1163): a saved set of projects and options that named people can open read only.
There is no public link and no token: a viewer signs in and sees only what their own access allows."""
from odoo import Command, _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

MAX_SHARES = 30
MAX_PROJECTS = 12
MAX_PEOPLE = 20
COLOUR_MODES = ("default", "status", "release")


class AgileRoadmapShare(models.Model):
    _name = "agile.roadmap.share"
    _description = "Agile Roadmap Share"
    _order = "name, id"

    name = fields.Char(required=True)
    owner_id = fields.Many2one("res.users", required=True, default=lambda self: self.env.user, ondelete="cascade", index=True)
    project_ids = fields.Many2many("project.project", "agile_roadmap_share_project_rel", "share_id", "project_id")
    user_ids = fields.Many2many("res.users", "agile_roadmap_share_user_rel", "share_id", "user_id")
    hide_done = fields.Boolean()
    epics_only = fields.Boolean()
    colour_by = fields.Selection([(mode, mode) for mode in COLOUR_MODES], default="default", required=True)

    @api.constrains("name", "project_ids", "user_ids")
    def _check_limits(self):
        for share in self:
            if not 1 <= len((share.name or "").strip()) <= 60:
                raise ValidationError(_("A shared roadmap needs a name of 1 to 60 characters."))
            if not 1 <= len(share.project_ids) <= MAX_PROJECTS:
                raise ValidationError(_("A shared roadmap holds 1 to %(max)s projects.", max=MAX_PROJECTS))
            if not 1 <= len(share.user_ids) <= MAX_PEOPLE:
                raise ValidationError(_("Share a roadmap with 1 to %(max)s people.", max=MAX_PEOPLE))

    # ---- who may be named ------------------------------------------------------------------

    @api.model
    def _candidates(self):
        """People the owner may name: members of the Agile projects the owner belongs to."""
        projects = self.env["agile.roadmap"]._projects([])
        members = self.env["agile.project.member"].sudo().search([("project_id", "in", projects.ids)])
        return (members.user_id - self.env.user).sorted("name")

    def _own(self):
        self.ensure_one()
        if self.owner_id != self.env.user:
            raise AccessError(_("Only the person who shared this roadmap can change it."))

    def _summary(self, mine):
        self.ensure_one()
        values = {
            "id": self.id, "name": self.name, "owner": self.owner_id.name, "mine": mine,
            "project_ids": self.project_ids.ids, "hide_done": self.hide_done,
            "epics_only": self.epics_only, "colour_by": self.colour_by,
        }
        if mine:
            values["user_ids"] = self.user_ids.ids
            values["people"] = ", ".join(self.user_ids.sorted("name").mapped("name"))
        return values

    # ---- calls from the Roadmap page -------------------------------------------------------

    @api.model
    def share_list(self):
        """The person's own shared roadmaps, those shared with them, and who they may name."""
        mine = self.search([("owner_id", "=", self.env.uid)])
        theirs = self.search([("owner_id", "!=", self.env.uid)])
        return {
            "mine": [share._summary(True) for share in mine],
            "shared": [share._summary(False) for share in theirs],
            "people": [{"id": user.id, "name": user.name} for user in self._candidates()],
        }

    @api.model
    def _clean(self, name, project_ids, user_ids, colour_by):
        name = (name or "").strip()
        if not name:
            raise UserError(_("Give the shared roadmap a name."))
        projects = self.env["agile.roadmap"]._projects([]).filtered(lambda p: p.id in set(project_ids or []))
        if not projects:
            raise UserError(_("Choose at least one project you belong to."))
        chosen = {int(uid) for uid in user_ids or []}
        if not chosen or not chosen <= set(self._candidates().ids):
            raise UserError(_("Name at least one person from your projects."))
        if colour_by not in COLOUR_MODES:
            colour_by = "default"
        return {
            "name": name, "project_ids": [Command.set(projects.ids)],
            "user_ids": [Command.set(sorted(chosen))], "colour_by": colour_by,
        }

    @api.model
    def share_create(self, name, project_ids, user_ids, hide_done=False, epics_only=False, colour_by="default"):
        if self.search_count([("owner_id", "=", self.env.uid)]) >= MAX_SHARES:
            raise UserError(_("You can share up to %(max)s roadmaps. Delete one first.", max=MAX_SHARES))
        values = self._clean(name, project_ids, user_ids, colour_by)
        values.update(hide_done=bool(hide_done), epics_only=bool(epics_only), owner_id=self.env.uid)
        return self.sudo().create(values).with_user(self.env.user)._summary(True)

    @api.model
    def share_update(self, share_id, user_ids):
        """Change who a shared roadmap goes to."""
        share = self.search([("id", "=", share_id), ("owner_id", "=", self.env.uid)])
        if not share:
            raise AccessError(_("Only the person who shared this roadmap can change it."))
        chosen = {int(uid) for uid in user_ids or []}
        if not chosen or not chosen <= set(self._candidates().ids):
            raise UserError(_("Name at least one person from your projects."))
        share.sudo().write({"user_ids": [Command.set(sorted(chosen))]})
        return share._summary(True)

    @api.model
    def share_delete(self, share_id):
        share = self.search([("id", "=", share_id), ("owner_id", "=", self.env.uid)])
        if not share:
            raise AccessError(_("Only the person who shared this roadmap can delete it."))
        share.sudo().unlink()
        return True

    @api.model
    def share_data(self, share_id):
        """A shared roadmap for its viewer: the saved options, with only the projects and items they may read."""
        share = self.search([("id", "=", share_id)])
        if not share:
            raise AccessError(_("This roadmap is not shared with you."))
        allowed = self.env["agile.roadmap"]._projects([]).filtered(lambda p: p.id in share.project_ids.ids)
        if not allowed:
            raise UserError(_("You cannot open any of the projects in this roadmap."))
        data = self.env["agile.roadmap"].roadmap_data(
            allowed.ids, hide_done=share.hide_done, epics_only=share.epics_only
        )
        return {
            "share": share._summary(share.owner_id == self.env.user),
            "hidden_projects": len(share.sudo().project_ids) - len(allowed),
            "data": data,
        }
