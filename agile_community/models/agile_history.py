"""Tabbed history of an issue (S-1128): comments, field changes and logged work in one feed."""
from odoo import _, fields, models
from odoo.tools import html2plaintext

HISTORY_LIMIT = 200


class ProjectTask(models.Model):
    _inherit = "project.task"

    def agile_history_feed(self):
        """Newest-first entries for the issue's History panel; each has a kind the panel filters on."""
        self.ensure_one()
        self.check_access("read")
        messages = self.env["mail.message"].search(
            [
                ("model", "=", "project.task"),
                ("res_id", "=", self.id),
                ("message_type", "in", ["comment", "notification"]),
            ],
            order="id desc",
            limit=HISTORY_LIMIT,
        )
        entries = []
        for message in messages:
            # Tracking values are not readable by every team member; the message already is.
            changes = [
                {
                    "field": value.field_id.field_description,
                    "old": value.old_value_char or "",
                    "new": value.new_value_char or "",
                }
                for value in message.sudo().tracking_value_ids
            ]
            text = html2plaintext(message.body or "").strip()
            is_comment = message.message_type == "comment" and not changes
            if not (text or changes):
                continue
            entries.append({
                "key": "m%s" % message.id,
                "kind": "comment" if is_comment else "history",
                "date": fields.Datetime.to_string(message.date),
                "author": self._agile_history_author(message),
                "text": text[:2000],
                "changes": changes,
                "note": bool(message.subtype_id and message.subtype_id.internal),
            })
        entries += self._agile_worklog_entries()
        entries.sort(key=lambda entry: (entry["date"], entry["key"]), reverse=True)
        return {
            "entries": entries[:HISTORY_LIMIT],
            "worklog_available": self._agile_worklog_available(),
        }

    @staticmethod
    def _agile_history_author(message):
        """The author's name, marked when the change was made by an AI agent (Q-1204)."""
        name = message.author_id.name or _("System")
        if message.author_id.sudo().user_ids.filtered("agile_is_agent"):
            return _("%s (agent)", name)
        return name

    def _agile_worklog_available(self):
        """True when time can be logged on issues; the Timesheets bridge turns it on."""
        return False

    def _agile_worklog_entries(self):
        """Logged-work entries in the same shape as the feed; the Timesheets bridge adds them."""
        return []
