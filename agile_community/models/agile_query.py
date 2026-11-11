"""The Agile query language (S-302): text such as `status = "In Progress" AND assignee = me`.

The text is read by a tokenizer and a small recursive-descent parser into nodes, then
compiled to an Odoo domain. Nothing is evaluated or concatenated into SQL: every word is
either a known field, a known operator, or a value that is looked up by name in the project.
"""
import difflib
import re
from datetime import datetime, time, timedelta

from dateutil.relativedelta import relativedelta

from odoo import _, fields
from odoo.fields import Domain
from odoo.tools.translate import LazyTranslate

_lt = LazyTranslate(__name__)

TOKEN = re.compile(r'''\s+|"(?:[^"\\]|\\.)*"|!=|!~|<=|>=|[=~<>(),]|[^\s"=!~<>(),]+|.''', re.S)
KEYWORDS = {"AND", "OR", "NOT", "IN", "IS", "EMPTY"}
CATEGORIES = {
    "backlog": "backlog", "ready": "ready", "in progress": "progress", "progress": "progress",
    "review": "review", "done": "done", "canceled": "canceled", "cancelled": "canceled", "to do": "ready", "todo": "ready",
}
CATEGORY_LABELS = ["Backlog", "To Do", "In Progress", "Review", "Done", "Canceled"]
PRIORITIES = {"low": "0", "medium": "1", "high": "2", "urgent": "3"}
PRIORITY_LABELS = ["Low", "Medium", "High", "Urgent"]
RESOLUTIONS = {
    "done": "done", "won't do": "wont_do", "wont do": "wont_do", "duplicate": "duplicate",
    "cannot reproduce": "cannot_reproduce",
}
RESOLUTION_LABELS = ["Done", "Won't do", "Duplicate", "Cannot reproduce"]
FUNCTIONS = {
    "assignee": ["me", "currentUser", "membersOf", "unassigned"],
    "reporter": ["me", "currentUser", "membersOf"],
    "sprint": ["currentSprint", "openSprints"],
}
DATE_FUNCTIONS = {
    "startofweek": _lt("Monday of this week"),
    "endofweek": _lt("Sunday of this week"),
    "startofmonth": _lt("first day of this month"),
    "endofmonth": _lt("last day of this month"),
}
DATE_FUNCTION_NAMES = {"startofweek": "startOfWeek", "endofweek": "endOfWeek",
                       "startofmonth": "startOfMonth", "endofmonth": "endOfMonth"}
RELATIVE = re.compile(r"^([+-])(\d+)([dwm])$")
OP_WORDS = {
    "=": _lt("is"), "!=": _lt("is not"), "~": _lt("contains"), "!~": _lt("does not contain"),
    "IN": _lt("is one of"), "NOT IN": _lt("is none of"),
    "IS EMPTY": _lt("is empty"), "IS NOT EMPTY": _lt("is not empty"),
}
ORDER_WORDS = {
    "date": {"<": _lt("is before"), "<=": _lt("is on or before"), ">": _lt("is after"), ">=": _lt("is on or after")},
    "number": {"<": _lt("is below"), "<=": _lt("is at most"), ">": _lt("is above"), ">=": _lt("is at least")},
}
SET_OPS = ["=", "!=", "IN", "NOT IN", "IS EMPTY", "IS NOT EMPTY"]
RELATION_OPS = SET_OPS + ["~", "!~"]
ORDER_OPS = ["=", "!=", "<", "<=", ">", ">=", "IS EMPTY", "IS NOT EMPTY"]

# name (lower case) -> label, domain path, kind, allowed operators, hint
FIELD_SPECS = {
    "project": ("Project", "project_id", "project", ["=", "!="], _lt("the project of the issue")),
    "status": ("Status", "stage_id", "status", SET_OPS, _lt("where the issue is in its workflow")),
    "statuscategory": ("Status category", "stage_id.agile_status", "category", ["=", "!=", "IN", "NOT IN"],
                       _lt("Backlog, Ready, In Progress, Review, Done or Canceled")),
    "assignee": ("Assignee", "user_ids", "user", RELATION_OPS, _lt("who works on the issue")),
    "reporter": ("Reporter", "create_uid", "user", ["=", "!=", "IN", "NOT IN", "~", "!~"], _lt("who created the issue")),
    "sprint": ("Sprint", "sprint_id", "sprint", RELATION_OPS, _lt("the sprint the issue is planned in")),
    "label": ("Label", "tag_ids", "label", RELATION_OPS, _lt("a tag on the issue")),
    "affectsversion": ("Affects version", "agile_affects_version_ids", "release", RELATION_OPS,
                       _lt("a release the issue was found in")),
    "type": ("Type", "agile_task_type_id", "type", SET_OPS[:4] + ["~", "!~"], _lt("Bug, Story, Task, Epic...")),
    "epic": ("Epic", "parent_id", "epic", RELATION_OPS, _lt("the epic the issue belongs to")),
    "priority": ("Priority", "priority", "priority", ["=", "!=", "IN", "NOT IN"], _lt("Low, Medium, High or Urgent")),
    "resolution": ("Resolution", "agile_resolution", "resolution", ["=", "!=", "IN", "NOT IN", "IS EMPTY", "IS NOT EMPTY"],
                   _lt("why a closed issue was closed: Done, Won't do, Duplicate or Cannot reproduce")),
    "points": ("Story points", "story_points", "number", ORDER_OPS, _lt("the estimate")),
    "votes": ("Votes", "agile_vote_count", "number", ORDER_OPS, _lt("how many people voted for the issue")),
    "created": ("Created", "create_date", "date", ORDER_OPS, _lt("when the issue was created")),
    "updated": ("Updated", "write_date", "date", ORDER_OPS, _lt("when the issue last changed")),
    "due": ("Due date", "date_deadline", "date", ORDER_OPS, _lt("the deadline")),
    "text": ("Text", "name", "text", ["~", "!~"], _lt("searches the title and the description")),
    "key": ("Key", "issue_key", "key", ["=", "!=", "IN", "NOT IN", "~"], _lt("the issue key, for example AUT-12")),
    "link": ("Linked to", "id", "links", SET_OPS, _lt("issues linked to another issue in any way, for example link = AUT-12")),
    "blocked": ("Blocked by", "depend_on_ids", "links", SET_OPS, _lt("issues waiting for another issue, for example blocked = AUT-12")),
    "blocks": ("Blocks", "dependent_ids", "links", SET_OPS, _lt("issues that hold up another issue, for example blocks = AUT-12")),
}
# Fields whose past is recorded by the chatter: field -> (task field, how the log keeps the value, takes values).
# Status and sprint are kept as record ids, priority as its label, assignees as a list of names, and the due date
# as a date only (so it can say that it changed but not from or to what).
HISTORY = {
    "status": ("stage_id", "id", True),
    "sprint": ("sprint_id", "id", True),
    "priority": ("priority", "label", True),
    "assignee": ("user_ids", "names", True),
    "due": ("date_deadline", "date", False),
}
WAS_OPS = ["WAS", "WAS NOT", "WAS IN", "WAS NOT IN"]
HISTORY_OPS = WAS_OPS + ["CHANGED"]
CHANGED_CLAUSES = ("FROM", "TO", "AFTER", "BEFORE", "BY")
CUSTOM_PREFIX = "cf:"
KEY_FORM = re.compile(r"^(.+)-(\d+)$")


def _plain_like(text):
    """A search word for ilike: % and _ are the person's own characters, not SQL wildcards (E2E-009)."""
    return (text or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _key_forms(value):
    """WEB-12 finds WEB-0012: the stored key is zero-padded (E2E-008). The written form is kept too."""
    forms = {value, value.upper()}
    match = KEY_FORM.match(value.strip())
    if match:
        prefix, number = match.group(1).upper(), int(match.group(2))
        forms.update({f"{prefix}-{number}", f"{prefix}-{number:04d}", f"{prefix}-{number:05d}"})
    return sorted(forms)
# A project's custom field is written field."Region" or field.Region (D-941); which operators fit depends on its type.
CUSTOM_OPS = {
    "text": ["=", "!=", "~", "!~", "IN", "NOT IN", "IS EMPTY", "IS NOT EMPTY"],
    "number": ORDER_OPS,
    "date": ORDER_OPS,
    "choice": RELATION_OPS,
    "user": SET_OPS,
    "multichoice": RELATION_OPS,
    "url": ["=", "!=", "~", "!~", "IN", "NOT IN", "IS EMPTY", "IS NOT EMPTY"],
    "users": SET_OPS,
}
BASIC_FIELDS = ["status", "assignee", "sprint", "type", "label", "epic", "due", "text"]
FIELD_NAMES = {
    "project": "project", "status": "status", "statuscategory": "statusCategory",
    "assignee": "assignee", "reporter": "reporter", "sprint": "sprint", "label": "label",
    "affectsversion": "affectsVersion",
    "type": "type", "epic": "epic", "priority": "priority", "resolution": "resolution", "points": "points", "votes": "votes",
    "created": "created", "updated": "updated", "due": "due", "text": "text", "key": "key",
    "link": "link", "blocked": "blocked", "blocks": "blocks",
}


# What ORDER BY can sort by: name -> (label, field of the issue). Dates and estimates with no value come last.
SORT_KEYS = {
    "rank": ("Backlog rank", "sequence"),
    "priority": ("Priority", "priority"),
    "created": ("Created", "create_date"),
    "updated": ("Updated", "write_date"),
    "due": ("Due date", "date_deadline"),
    "points": ("Story points", "story_points"),
    "votes": ("Votes", "agile_vote_count"),
    "key": ("Key", "id"),
    "title": ("Title", "name"),
    "status": ("Status", "stage_id"),
}


class QueryError(ValueError):
    """A problem in the query text, in words a person can act on, with where it is."""

    def __init__(self, message, start=0, end=0):
        super().__init__(message)
        self.message, self.start, self.end = message, start, end


class Token:
    def __init__(self, kind, text, start, end, value=None):
        self.kind, self.text, self.start, self.end = kind, text, start, end
        self.value = text if value is None else value

    def is_word(self, *words):
        return self.kind == "word" and self.text.upper() in words


def tokenize(text):
    tokens = []
    for match in TOKEN.finditer(text):
        raw = match.group()
        start, end = match.span()
        if raw.isspace():
            continue
        if raw.startswith('"'):
            if len(raw) < 2 or not raw.endswith('"'):
                raise QueryError(_("A quote is not closed."), start, end)
            tokens.append(Token("string", raw, start, end, re.sub(r"\\(.)", r"\1", raw[1:-1])))
        elif raw in ("=", "!=", "~", "!~", "<", "<=", ">", ">="):
            tokens.append(Token("op", raw, start, end))
        elif raw == "(":
            tokens.append(Token("lparen", raw, start, end))
        elif raw == ")":
            tokens.append(Token("rparen", raw, start, end))
        elif raw == ",":
            tokens.append(Token("comma", raw, start, end))
        elif raw == "!":
            raise QueryError(_("'%s' is not allowed here.", raw), start, end)
        else:
            tokens.append(Token("word", raw, start, end))
    return tokens


def split_order(tokens):
    """Cut a query's tokens at ORDER BY: (condition tokens, [(key, descending)], the sort in words).

    ORDER is only read as the keyword when BY follows it and a condition has come before it (or nothing has).
    """
    cut = next((
        i for i, token in enumerate(tokens[:-1])
        if token.is_word("ORDER") and tokens[i + 1].is_word("BY")
        and (i == 0 or tokens[i - 1].kind in ("word", "string", "rparen"))
    ), None)
    if cut is None:
        return tokens, [], ""
    rest, items, index = tokens[cut + 2:], [], 0
    if not rest:
        end = tokens[cut + 1].end
        raise QueryError(_("Say what to sort by, for example: ORDER BY priority DESC"), end, end)
    while index < len(rest):
        token = rest[index]
        key = token.value.lower() if token.kind in ("word", "string") else ""
        if key not in SORT_KEYS:
            raise QueryError(
                _("'%(value)s' cannot be sorted. Choose from: %(all)s.", value=token.text, all=", ".join(SORT_KEYS)),
                token.start, token.end,
            )
        index += 1
        descending = False
        if index < len(rest) and rest[index].is_word("ASC", "DESC"):
            descending = rest[index].is_word("DESC")
            index += 1
        items.append((key, descending))
        if index < len(rest):
            if rest[index].kind != "comma" or index + 1 >= len(rest):
                raise QueryError(_("Separate sort keys with a comma."), rest[index].start, rest[index].end)
            index += 1
    words = ", ".join(
        str(SORT_KEYS[key][0]) + (str(_(" descending")) if descending else "") for key, descending in items
    )
    return tokens[:cut], items, str(_("sorted by %s", words))


class Condition:
    def __init__(self, field, op, values, start, end, clauses=None):
        self.field, self.op, self.values, self.start, self.end = field, op, values, start, end
        self.clauses = clauses or {}  # CHANGED only: FROM, TO, AFTER, BEFORE, BY -> value token


class Group:
    def __init__(self, kind, children):
        self.kind, self.children = kind, children  # "and", "or" or "not"


class Parser:
    def __init__(self, tokens, text):
        self.tokens, self.text, self.pos = tokens, text, 0

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self):
        token = self.peek()
        self.pos += 1
        return token

    def end_error(self, message):
        end = len(self.text)
        return QueryError(message, end, end)

    def parse(self):
        if not self.tokens:
            raise self.end_error(_("Write a condition, for example: status = Done"))
        node = self.expression()
        token = self.peek()
        if token:
            if token.kind == "rparen":
                raise QueryError(_("A closing bracket has no opening bracket."), token.start, token.end)
            raise QueryError(_("Join conditions with AND or OR."), token.start, token.end)
        return node

    def expression(self):
        nodes = [self.conjunction()]
        while self.peek() and self.peek().is_word("OR"):
            self.take()
            nodes.append(self.conjunction())
        return nodes[0] if len(nodes) == 1 else Group("or", nodes)

    def conjunction(self):
        nodes = [self.negation()]
        while self.peek() and self.peek().is_word("AND"):
            self.take()
            nodes.append(self.negation())
        return nodes[0] if len(nodes) == 1 else Group("and", nodes)

    def negation(self):
        token = self.peek()
        if token and token.is_word("NOT"):
            self.take()
            return Group("not", [self.negation()])
        return self.atom()

    def atom(self):
        token = self.take()
        if token is None:
            raise self.end_error(_("The query stops too early. Add a condition after AND, OR or NOT."))
        if token.kind == "lparen":
            node = self.expression()
            closing = self.take()
            if closing is None or closing.kind != "rparen":
                raise self.end_error(_("A closing bracket is missing at the end."))
            return node
        if token.kind != "word":
            raise QueryError(_("Start a condition with a field name, for example status."), token.start, token.end)
        return self.condition(token)

    def condition(self, field_token):
        key = field_token.text.lower()
        custom = key.startswith("field.")
        if custom:
            name = field_token.text[len("field."):]
            if not name:
                quoted = self.take()
                if quoted is None or quoted.kind != "string":
                    raise QueryError(
                        _('Write the field name after field., for example field."Region".'),
                        field_token.start, field_token.end,
                    )
                name = quoted.value
            key = CUSTOM_PREFIX + name
        if not custom and key not in FIELD_SPECS:
            close = difflib.get_close_matches(key, FIELD_SPECS, n=1)
            hint = _(" Did you mean '%s'?", FIELD_NAMES[close[0]]) if close else ""
            raise QueryError(
                _("Unknown field '%(field)s'.%(hint)s", field=field_token.text, hint=hint),
                field_token.start, field_token.end,
            )
        allowed = sorted(set(sum(CUSTOM_OPS.values(), [])), key=str) if custom else FIELD_SPECS[key][3]
        token = self.take()
        if token is None:
            raise self.end_error(_("Add an operator after %(field)s, for example =.", field=self.display(key)))
        start = field_token.start
        if token.is_word("IS"):
            nxt = self.take()
            negate = nxt is not None and nxt.is_word("NOT")
            if negate:
                nxt = self.take()
            if nxt is None or not nxt.is_word("EMPTY"):
                raise self.end_error(_("Write IS EMPTY or IS NOT EMPTY."))
            op = "IS NOT EMPTY" if negate else "IS EMPTY"
            self.check_op(key, op, token, allowed)
            return Condition(key, op, [], start, nxt.end)
        if token.is_word("WAS", "CHANGED"):
            return self.history(key, custom, field_token, token)
        if token.is_word("NOT"):
            nxt = self.take()
            if nxt is None or not nxt.is_word("IN"):
                raise QueryError(_("Write NOT IN (a, b)."), token.start, token.end)
            op = "NOT IN"
        elif token.is_word("IN"):
            op = "IN"
        elif token.kind == "op":
            op = token.text
        else:
            raise QueryError(
                _("Add an operator after %(field)s, for example = or ~.", field=self.display(key)),
                token.start, token.end,
            )
        self.check_op(key, op, token, allowed)
        if op in ("IN", "NOT IN"):
            values, end = self.value_list()
        else:
            value = self.take()
            if value is None:
                raise self.end_error(_("Add a value after %(field)s %(op)s.", field=self.display(key), op=op))
            values, end = [self.value(value)], self.skip_call(value)
        return Condition(key, op, values, start, end)

    def history(self, key, custom, field_token, word):
        """`status WAS Review`, `status WAS NOT IN (a, b)` and `status CHANGED FROM a TO b AFTER -7d BY me`."""
        if custom or key not in HISTORY:
            names = ", ".join(FIELD_NAMES[k] for k in HISTORY)
            raise QueryError(
                _("%(field)s has no history to search. Fields with a history: %(all)s.",
                  field=self.display(key), all=names), word.start, word.end)
        takes_values = HISTORY[key][2]
        start = field_token.start
        if word.is_word("CHANGED"):
            clauses, end = {}, word.end
            while self.peek() and self.peek().is_word(*CHANGED_CLAUSES):
                clause = self.take()
                name = clause.text.upper()
                if name in clauses:
                    raise QueryError(_("%s is written twice.", name), clause.start, clause.end)
                if name in ("FROM", "TO") and not takes_values:
                    raise QueryError(
                        _("The history of %(field)s only says that it changed, so leave out %(word)s.",
                          field=self.display(key), word=name), clause.start, clause.end)
                value = self.take()
                if value is None:
                    raise self.end_error(_("Add a value after %s.", name))
                clauses[name] = self.value(value)
                end = self.skip_call(value)
            return Condition(key, "CHANGED", [], start, end, clauses)
        if not takes_values:
            raise QueryError(
                _("%(field)s can only be written as CHANGED, for example %(field)s CHANGED AFTER -7d.",
                  field=self.display(key)), word.start, word.end)
        op = "WAS"
        nxt = self.peek()
        if nxt and nxt.is_word("NOT"):
            self.take()
            op = "WAS NOT"
            nxt = self.peek()
        if nxt and nxt.is_word("IN"):
            self.take()
            op += " IN"
            values, end = self.value_list()
        else:
            value = self.take()
            if value is None:
                raise self.end_error(_("Add a value after %(field)s %(op)s.", field=self.display(key), op=op))
            values, end = [self.value(value)], self.skip_call(value)
        return Condition(key, op, values, start, end)

    @staticmethod
    def display(key):
        return key[len(CUSTOM_PREFIX):] if key.startswith(CUSTOM_PREFIX) else FIELD_NAMES[key]

    def check_op(self, key, op, token, allowed):
        if op not in allowed:
            raise QueryError(
                _("'%(op)s' does not work with %(field)s. Use %(allowed)s.",
                  op=op, field=self.display(key), allowed=", ".join(allowed)),
                token.start, token.end,
            )

    def value(self, token):
        if token.kind not in ("word", "string") or (token.kind == "word" and token.text.upper() in KEYWORDS):
            raise QueryError(_("Write a value here, with quotes if it has spaces."), token.start, token.end)
        return token

    def skip_call(self, token):
        """`currentSprint()` is accepted as well as `currentSprint`."""
        nxt, after = self.peek(), self.tokens[self.pos + 1] if self.pos + 1 < len(self.tokens) else None
        if token.kind == "word" and nxt and nxt.kind == "lparen" and after and after.kind == "rparen":
            self.pos += 2
            return after.end
        return token.end

    def value_list(self):
        opening = self.take()
        if opening is None or opening.kind != "lparen":
            raise self.end_error(_("Put the values in brackets: IN (a, b)."))
        values = []
        while True:
            token = self.take()
            if token is None:
                raise self.end_error(_("A closing bracket is missing at the end."))
            values.append(self.value(token))
            sep = self.take()
            if sep is None:
                raise self.end_error(_("A closing bracket is missing at the end."))
            if sep.kind == "rparen":
                return values, sep.end
            if sep.kind != "comma":
                raise QueryError(_("Separate values with commas."), sep.start, sep.end)


class AgileQuery:
    """Reads and compiles query text for one project, on behalf of the environment's user."""

    def __init__(self, env, project):
        self.env = env
        self.project = project

    # ---- compile ----------------------------------------------------------------

    def compile(self, text):
        """Return (domain, words). Raises QueryError."""
        tokens, items, sorted_words = split_order(tokenize(text))
        if not tokens and items:
            return [], sorted_words
        tree = Parser(tokens, text).parse()
        domain = self._domain(tree)
        words = self._words(tree)
        return list(domain), f"{words}, {sorted_words}" if sorted_words else words

    def order(self, text):
        """The ORDER BY of a query as an Odoo order string ('' when it has none); ties fall back to the key."""
        _tokens, items, _words = split_order(tokenize(text or ""))
        return ", ".join(
            f"{SORT_KEYS[key][1]} {'desc' if descending else 'asc'} nulls last" for key, descending in items
        )

    def _domain(self, node):
        if isinstance(node, Condition):
            return self._leaf(node)
        parts = [self._domain(child) for child in node.children]
        if node.kind == "not":
            return ~parts[0]
        return Domain.AND(parts) if node.kind == "and" else Domain.OR(parts)

    def _custom_field(self, cond):
        name = cond.field[len(CUSTOM_PREFIX):]
        project = self.project.sudo()
        if "agile_custom_field_ids" not in project._fields:
            raise QueryError(
                _("Custom fields in searches come with Agile Boards Pro."), cond.start, cond.end,
            )
        fields_ = project.agile_custom_field_ids
        found = fields_.filtered(lambda f: f.name.lower() == name.lower())
        if not found:
            known = ", ".join(f'"{f.name}"' for f in fields_) or _("none yet")
            raise QueryError(
                _("This project has no custom field '%(name)s'. Its custom fields: %(known)s.", name=name, known=known),
                cond.start, cond.end,
            )
        return found[0]

    def _custom_leaf(self, cond):
        field = self._custom_field(cond)
        kind, op = field.field_type, cond.op
        if op not in CUSTOM_OPS[kind]:
            raise QueryError(
                _("'%(op)s' does not work with %(field)s. Use %(allowed)s.",
                  op=op, field=field.name, allowed=", ".join(CUSTOM_OPS[kind])),
                cond.start, cond.end,
            )
        has_value = Domain("agile_custom_value_ids", "any", Domain("field_id", "=", field.id) & Domain("display_text", "!=", False))
        if op == "IS EMPTY":
            return ~has_value
        if op == "IS NOT EMPTY":
            return has_value
        negative = op in ("!=", "NOT IN", "!~")
        match = {"!=": "=", "NOT IN": "IN", "!~": "~"}.get(op, op)
        tokens = cond.values
        if kind in ("text", "url"):
            column = "value_char"
            if match == "~":
                value_domain = Domain(column, "ilike", _plain_like(tokens[0].value))
            else:
                value_domain = Domain(column, "in", [t.value for t in tokens])
        elif kind in ("number", "date"):
            column = "value_number" if kind == "number" else "value_date"
            value = self._number(tokens[0]) if kind == "number" else self._date(tokens[0]).isoformat()
            negative = op == "!="
            value_domain = Domain(column, "=" if negative else op, value)
        elif kind in ("choice", "multichoice"):
            choice_column = "value_choice_id" if kind == "choice" else "value_choice_ids"
            if match == "~":
                value_domain = Domain(choice_column + ".name", "ilike", tokens[0].value)
            else:
                wanted = {t.value.strip().lower() for t in tokens}
                choices = field.choice_ids.filtered(lambda c: c.name.lower() in wanted)
                missing = wanted - {c.name.lower() for c in choices}
                if missing:
                    names = ", ".join(c.name for c in field.choice_ids)
                    raise QueryError(
                        _("'%(value)s' is not a choice of %(field)s. Choose from: %(all)s.",
                          value=sorted(missing)[0], field=field.name, all=names),
                        cond.start, cond.end,
                    )
                value_domain = Domain(choice_column, "in", choices.ids)
        else:
            ids = []
            for token in tokens:
                ids.extend(self._resolve("user", token) if token.value.lower() != "unassigned" else [])
            value_domain = Domain("value_user_id" if kind == "user" else "value_user_ids", "in", ids)
        positive = Domain("agile_custom_value_ids", "any", Domain("field_id", "=", field.id) & value_domain)
        return ~positive if negative else positive

    def _leaf(self, cond):
        if cond.field.startswith(CUSTOM_PREFIX):
            return self._custom_leaf(cond)
        label, path, kind, _allowed, _hint = FIELD_SPECS[cond.field]
        op = cond.op
        if op in HISTORY_OPS:
            return self._history_leaf(cond)
        if kind == "links":
            return self._link_leaf(cond, path)
        if op == "IS EMPTY":
            return self._empty(cond, path, kind, True)
        if op == "IS NOT EMPTY":
            return self._empty(cond, path, kind, False)
        if kind == "text":
            word = _plain_like(cond.values[0].value)
            term = Domain.OR([Domain("name", "ilike", word), Domain("description", "ilike", word)])
            return ~term if op == "!~" else term
        if kind == "key":
            values = [v.value for v in cond.values]
            if op in ("~", "!~"):
                return Domain(path, "ilike" if op == "~" else "not ilike", _plain_like(values[0]))
            positive = op in ("=", "IN")
            wanted = [form for value in (values[:1] if op in ("=", "!=") else values) for form in _key_forms(value)]
            # A key the issue had before a move to another project still finds it.
            found = Domain(path, "in", wanted) | Domain("agile_old_key_ids", "any", Domain("key", "in", wanted))
            return found if positive else ~found
        if kind == "number":
            return Domain(path, op, self._number(cond.values[0]))
        if kind == "date":
            return Domain(path, op, self._date(cond.values[0]).isoformat())
        if kind == "project":
            if cond.values[0].value.lower() != (self.project.name or "").lower():
                raise QueryError(
                    _("This filter belongs to the project '%s'. Filters search one project.", self.project.name),
                    cond.values[0].start, cond.values[0].end,
                )
            return Domain("project_id", "=" if op == "=" else "!=", self.project.id)
        if op in ("~", "!~"):
            domain = Domain(path + ".name", "ilike", cond.values[0].value)
            return domain if op == "~" else ~domain
        ids = []
        special = None
        for token in cond.values:
            resolved = self._resolve(kind, token)
            if resolved == "unassigned":
                special = True
            else:
                ids.extend(resolved)
        positive = op in ("=", "IN")
        if special:
            return Domain(path, "=" if positive else "!=", False)
        return Domain(path, "in" if positive else "not in", ids)

    # ---- history (K-1034): read from the chatter's tracked changes ----------------------

    def _history_leaf(self, cond):
        name, mode, _takes = HISTORY[cond.field]
        if cond.op == "CHANGED":
            return Domain("id", "in", self._changed_ids(cond, name, mode))
        wanted = self._history_values(cond.field, cond.values)
        if mode == "label":
            current = Domain(name, "in", [PRIORITIES[w.lower()] for w in wanted])
        elif mode == "names":
            current = Domain("user_ids.name", "in", wanted)
        else:
            current = Domain(name, "in", wanted)
        past = self._tracking_task_ids(name, mode, "old", wanted)
        held = current | Domain("id", "in", past)
        return held if cond.op in ("WAS", "WAS IN") else ~held

    def _history_values(self, field, tokens):
        """What the written values mean for the log: record ids, priority labels or people's names."""
        _name, mode, _takes = HISTORY[field]
        kind = FIELD_SPECS[field][2]
        out = []
        for token in tokens:
            if token.value.strip().lower() == "unassigned":
                raise QueryError(_("A history can name people, not 'unassigned'."), token.start, token.end)
            resolved = self._resolve(kind, token)
            if mode == "label":
                out.extend(PRIORITY_LABELS[int(code)] for code in resolved)
            elif mode == "names":
                out.extend(self.env["res.users"].sudo().browse(resolved).mapped("name"))
            else:
                out.extend(resolved)
        return out

    def _history_users(self, token):
        return self._resolve("user", token) if token.value.strip().lower() != "unassigned" else []

    def _changed_ids(self, cond, name, mode):
        clauses = cond.clauses
        extra = []
        if "AFTER" in clauses:
            extra.append(Domain("create_date", ">=", datetime.combine(self._date(clauses["AFTER"]), time.min)))
        if "BEFORE" in clauses:
            extra.append(Domain("create_date", "<", datetime.combine(self._date(clauses["BEFORE"]), time.min)))
        if "BY" in clauses:
            extra.append(Domain("create_uid", "in", self._history_users(clauses["BY"])))
        sides = {}
        for clause, side in (("FROM", "old"), ("TO", "new")):
            if clause in clauses:
                sides[side] = self._history_values(cond.field, [clauses[clause]])
        return self._tracking_task_ids(name, mode, None, sides, extra)

    def _task_ids(self):
        if not hasattr(self, "_project_task_ids"):
            self._project_task_ids = self.env["project.task"].sudo().with_context(active_test=False).search(
                [("project_id", "=", self.project.id)]).ids
        return self._project_task_ids

    def _tracking_task_ids(self, name, mode, side, wanted, extra=()):
        """Ids of this project's issues with a logged change of the field.

        `wanted` is the values the old (or new) side must have; with no side it is {"old": [...], "new": [...]}.
        """
        sides = {side: wanted} if side else wanted
        field = self.env["ir.model.fields"]._get("project.task", name)
        domain = [
            ("field_id", "=", field.id), ("mail_message_id.model", "=", "project.task"),
            ("mail_message_id.res_id", "in", self._task_ids()),
        ] + list(extra)
        for which, values in sides.items():
            if mode == "id":
                domain.append((f"{which}_value_integer", "in", values))
            elif mode == "label":
                domain.append((f"{which}_value_char", "in", values))
            else:  # names: look for the text first, then check it is a whole name
                domain.append(Domain.OR([Domain(f"{which}_value_char", "ilike", n) for n in values]))
        rows = self.env["mail.tracking.value"].sudo().search_fetch(
            domain, ["mail_message_id", "old_value_char", "new_value_char"])
        if mode == "names":
            rows = rows.filtered(lambda row: all(
                {n.strip().lower() for n in row[f"{which}_value_char"].split(",")} & {v.lower() for v in values}
                for which, values in sides.items()))
        messages = self.env["mail.message"].sudo().search_fetch([("id", "in", rows.mail_message_id.ids)], ["res_id"])
        return list({m.res_id for m in messages})

    def _linked_ids(self):
        """Every issue of this project that has a link of any type, in either direction."""
        env = self.env
        Task = env["project.task"].sudo()
        rows = env["agile_community.issue_link"].sudo().search([
            "|", ("issue_a_id.project_id", "=", self.project.id), ("issue_b_id.project_id", "=", self.project.id),
        ])
        ids = set(rows.issue_a_id.ids) | set(rows.issue_b_id.ids)
        ids |= set(Task.search([
            ("project_id", "=", self.project.id), "|", ("depend_on_ids", "!=", False), ("dependent_ids", "!=", False),
        ]).ids)
        return ids

    def _link_partners(self, ids):
        """The issues linked, in any way, to one of the given issues."""
        env = self.env
        Task = env["project.task"].sudo()
        rows = env["agile_community.issue_link"].sudo().search([
            "|", ("issue_a_id", "in", list(ids)), ("issue_b_id", "in", list(ids)),
        ])
        partners = set(rows.issue_a_id.ids) | set(rows.issue_b_id.ids)
        tasks = Task.browse(list(ids))
        partners |= set(tasks.depend_on_ids.ids) | set(tasks.dependent_ids.ids)
        return partners - set(ids) if len(ids) == 1 else partners

    def _link_leaf(self, cond, path):
        """link, blocked and blocks: compared with issue keys, or checked for being empty."""
        op = cond.op
        if op in ("IS EMPTY", "IS NOT EMPTY"):
            empty = op == "IS EMPTY"
            if cond.field == "link":
                return Domain("id", "not in" if empty else "in", list(self._linked_ids()))
            return Domain(path, "=" if empty else "!=", False)
        ids = []
        for token in cond.values:
            task = self.env["project.task"].search([("issue_key", "=ilike", token.value.strip())], limit=1)
            if not task:
                raise QueryError(_("No issue has the key '%s'.", token.value), token.start, token.end)
            ids.append(task.id)
        positive = op in ("=", "IN")
        if cond.field == "link":
            return Domain("id", "in" if positive else "not in", list(self._link_partners(ids)))
        return Domain(path, "in" if positive else "not in", ids)

    def _empty(self, cond, path, kind, empty):
        if kind == "number":
            return Domain("story_points_estimated", "=", not empty)
        return Domain(path, "=" if empty else "!=", False)

    def _number(self, token):
        try:
            return float(token.value)
        except ValueError:
            raise QueryError(_("'%s' is not a number.", token.value), token.start, token.end) from None

    def _date(self, token):
        value = token.value.strip()
        today = fields.Date.context_today(self.env["project.task"])
        if value.lower() == "today":
            return today
        if value.lower() in DATE_FUNCTIONS:
            return self._date_function(value.lower(), today)
        match = RELATIVE.match(value.lower())
        if match:
            amount = int(match.group(2)) * (1 if match.group(1) == "+" else -1)
            if match.group(3) == "m":
                return today + relativedelta(months=amount)
            return today + timedelta(days=amount * (7 if match.group(3) == "w" else 1))
        try:
            return fields.Date.from_string(value) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) else self._bad_date(token)
        except ValueError:
            return self._bad_date(token)

    @staticmethod
    def _date_function(name, today):
        if name == "startofweek":
            return today - timedelta(days=today.weekday())
        if name == "endofweek":
            return today + timedelta(days=6 - today.weekday())
        if name == "startofmonth":
            return today.replace(day=1)
        return today + relativedelta(day=31)  # last day of the month

    def _bad_date(self, token):
        raise QueryError(
            _("'%s' is not a date. Use 2026-10-27, today, -7d, -2w, -1m or startOfWeek.", token.value),
            token.start, token.end,
        )

    # ---- values looked up by name ----------------------------------------------

    def _candidates(self, kind):
        """(record, [names it may be written as]) for the values of a field kind."""
        env, project = self.env, self.project
        if kind == "status":
            stages = project.with_context(active_test=False).type_ids.filtered("agile_status")
            return [(s, [s.name]) for s in stages]
        if kind == "type":
            types = env["agile_community.task_type"].sudo().search([
                "|", ("project_ids", "=", False), ("project_ids", "=", project.id)])
            return [(t, [t.name]) for t in types]
        if kind == "sprint":
            return [(s, [s.name]) for s in env["project.sprint"].sudo().search([("project_id", "=", project.id)])]
        if kind in ("user",):
            users = project.agile_member_ids.user_id
            return [(u, [u.name, u.login]) for u in users]
        if kind == "label":
            return [(t, [t.name]) for t in env["project.tags"].sudo().search([])]
        if kind == "release":
            return [(v, [v.name]) for v in env["project.version"].sudo().with_context(active_test=False).search(
                [("project_id", "=", project.id)])]
        if kind == "epic":
            epics = env["project.task"].sudo().search([
                ("project_id", "=", project.id), ("agile_is_epic", "=", True)])
            return [(e, [e.name] + ([e.issue_key] if e.issue_key else [])) for e in epics]
        return []

    def _resolve(self, kind, token):
        value = token.value.strip()
        low = value.lower()
        if kind == "category":
            if low not in CATEGORIES:
                raise QueryError(_("'%(value)s' is not a status category. Choose from: %(all)s.",
                                   value=value, all=", ".join(CATEGORY_LABELS)), token.start, token.end)
            return [CATEGORIES[low]]
        if kind == "priority":
            if low not in PRIORITIES:
                raise QueryError(_("'%(value)s' is not a priority. Choose from: %(all)s.",
                                   value=value, all=", ".join(PRIORITY_LABELS)), token.start, token.end)
            return [PRIORITIES[low]]
        if kind == "resolution":
            if low not in RESOLUTIONS:
                raise QueryError(_("'%(value)s' is not a resolution. Choose from: %(all)s.",
                                   value=value, all=", ".join(RESOLUTION_LABELS)), token.start, token.end)
            return [RESOLUTIONS[low]]
        if kind == "user":
            if low in ("me", "currentuser"):
                return [self.env.uid]
            if low == "membersof":
                return self.project.agile_member_ids.user_id.ids
            if low == "unassigned":
                return "unassigned"
        if kind == "sprint" and low in ("currentsprint", "opensprints"):
            states = ["in_progress"] if low == "currentsprint" else ["draft", "in_progress"]
            return self.env["project.sprint"].sudo().search([
                ("project_id", "=", self.project.id), ("state", "in", states)]).ids
        found = [rec for rec, names in self._candidates(kind) if low in [n.lower() for n in names if n]]
        if not found:
            names = [names[0] for _rec, names in self._candidates(kind)]
            plural = {"status": _("statuses"), "type": _("types"), "sprint": _("sprints"), "user": _("people"),
                      "label": _("labels"), "epic": _("epics"), "release": _("releases")}[kind]
            raise QueryError(
                _("'%(value)s' is not one of this project's %(plural)s.%(all)s",
                  value=value, plural=plural,
                  all=(" " + _("Choose from: %s.", ", ".join(names[:12]))) if names else ""),
                token.start, token.end,
            )
        return [rec.id for rec in found]

    # ---- the query in words ------------------------------------------------------

    def _words(self, node, nested=False):
        if isinstance(node, Condition):
            return self._words_condition(node)
        if node.kind == "not":
            return _("not (%s)", self._words(node.children[0], True))
        joiner = _(", and ") if node.kind == "and" else _(", or ")
        text = joiner.join(self._words(child, True) for child in node.children)
        return f"({text})" if nested else text

    def _words_condition(self, cond):
        if cond.field.startswith(CUSTOM_PREFIX):
            kind = self._custom_field(cond).field_type
            label = cond.field[len(CUSTOM_PREFIX):]
        else:
            label, _path, kind, _allowed, _hint = FIELD_SPECS[cond.field]
        if cond.op in HISTORY_OPS:
            return self._history_words(cond, label)
        words = (ORDER_WORDS.get(kind, {}) if cond.op in ("<", "<=", ">", ">=") else OP_WORDS)
        if kind == "date" and cond.op in ("<", "<=", ">", ">="):
            words = ORDER_WORDS["date"]
        op = words.get(cond.op) or OP_WORDS[cond.op]
        values = [self._value_words(cond.field, t) for t in cond.values]
        return " ".join(part for part in (label, str(op), ", ".join(values)) if part)

    def _history_words(self, cond, label):
        if cond.op != "CHANGED":
            phrase = {"WAS": _("was"), "WAS NOT": _("was never"), "WAS IN": _("was one of"),
                      "WAS NOT IN": _("was none of")}[cond.op]
            return " ".join([label, str(phrase), ", ".join(self._value_words(cond.field, t) for t in cond.values)])
        parts = [label, str(_("changed"))]
        for clause, word in (("FROM", _("from")), ("TO", _("to")), ("AFTER", _("after")),
                             ("BEFORE", _("before")), ("BY", _("by"))):
            if clause in cond.clauses:
                parts += [str(word), self._value_words(cond.field, cond.clauses[clause])]
        return " ".join(parts)

    def _value_words(self, field, token):
        low = token.value.lower()
        if low in ("me", "currentuser"):
            return str(_("you"))
        if low == "membersof":
            return str(_("the team"))
        if low in DATE_FUNCTIONS:
            return str(DATE_FUNCTIONS[low])
        return token.value

    # ---- the query as chip rows (Basic mode) ----------------------------------------

    def to_rows(self, text):
        """The query as rows of one operator and value each, or None when only the bar can show it.

        A trailing ORDER BY is carried as ``sort`` text, so Basic keeps the sort and shows it.
        """
        try:
            tokens, items, _words = split_order(tokenize(text))
            sort = (
                "ORDER BY " + ", ".join(f"{key} DESC" if desc else key for key, desc in items) if items else ""
            )
            if not tokens:
                return {"match_any": False, "rows": [], "sort": sort} if items else None
            tree = Parser(tokens, text).parse()
        except QueryError:
            return None
        if isinstance(tree, Condition):
            nodes, match_any = [tree], False
        elif isinstance(tree, Group) and tree.kind in ("and", "or") and all(
            isinstance(child, Condition) for child in tree.children
        ):
            nodes, match_any = tree.children, tree.kind == "or"
        else:
            return None
        rows = []
        for cond in nodes:
            if cond.field not in BASIC_FIELDS or cond.op in ("IN", "NOT IN") + tuple(HISTORY_OPS):
                return None
            rows.append({
                "field": FIELD_NAMES[cond.field], "op": cond.op,
                "value": cond.values[0].value if cond.values else "",
            })
        return {"match_any": match_any, "rows": rows, "sort": sort}

    def basic_blockers(self, text):
        """What keeps a query out of Basic, in words (empty when Basic can show it)."""
        try:
            tokens, _items, _words = split_order(tokenize(text))
        except QueryError:
            return []
        found = []
        if any(token.kind in ("lparen", "rparen") for token in tokens):
            found.append(_("brackets"))
        if any(token.is_word("NOT") for token in tokens):
            found.append(_("NOT"))
        if any(token.is_word("IN") for token in tokens):
            found.append(_("IN"))
        if any(token.is_word("WAS", "CHANGED") for token in tokens):
            found.append(_("history words (WAS, CHANGED)"))
        if not found and self.to_rows(text) is None:
            found.append(_("a field or a mix of AND and OR that Basic does not offer"))
        return [str(item) for item in found]

    def basic_options(self):
        """What the Basic rows offer per field: operators and, where they exist, the values."""
        options = []
        for key in BASIC_FIELDS:
            label, _path, kind, allowed, _hint = FIELD_SPECS[key]
            words = ORDER_WORDS.get(kind, {})
            ops = [
                {"op": op, "label": str(words.get(op) or OP_WORDS[op])}
                for op in allowed if op not in ("IN", "NOT IN")
            ]
            values = [value for value, _h in self._value_hints(key)] if kind not in ("date", "text") else None
            options.append({
                "field": FIELD_NAMES[key], "label": str(label), "kind": kind, "ops": ops, "values": values,
            })
        return options

    # ---- autocomplete -------------------------------------------------------------

    def suggest(self, text, position=None):
        """What can come next at the cursor: {"start", "end", "items": [{label, insert, hint}]}."""
        end = len(text) if position is None else max(0, min(position, len(text)))
        before = text[:end]
        partial = re.search(r'"[^"]*$|[^\s"=!~<>(),]+$', before)
        start = partial.start() if partial else end
        prefix = before[start:].lstrip('"').lower()
        try:
            tokens = tokenize(before[:start])
        except QueryError:
            return {"start": start, "end": end, "items": []}
        sort_at = next((
            i for i, token in enumerate(tokens[:-1])
            if token.is_word("ORDER") and tokens[i + 1].is_word("BY")
        ), None)
        if sort_at is not None:
            tail = tokens[sort_at + 2:]
            after_key = bool(tail) and tail[-1].kind != "comma" and not tail[-1].is_word("ASC", "DESC")
            if tail and tail[-1].is_word("ASC", "DESC"):
                items = [(",", "")]
            elif after_key:
                items = [("ASC", _("lowest first")), ("DESC", _("highest first")), (",", "")]
            else:
                items = [(key, label) for key, (label, _path) in SORT_KEYS.items()]
            matched = [i for i in items if i[0].lower().startswith(prefix)]
            return {
                "start": start, "end": end,
                "items": [{"label": label, "insert": label, "hint": str(hint)} for label, hint in matched],
            }
        state, field, depth, clause, used = "field", None, 0, None, set()
        for index, token in enumerate(tokens):
            if state in ("field",):
                if token.kind == "lparen":
                    depth += 1
                elif token.is_word("NOT"):
                    pass
                elif token.kind == "word":
                    field, state = token.text.lower(), "op"
            elif state == "op":
                if token.is_word("WAS"):
                    state = "was"
                elif token.is_word("CHANGED"):
                    state, clause, used = "changed", None, set()
                elif token.is_word("IS"):
                    state = "is"
                elif token.is_word("NOT"):
                    state = "not_in"
                elif token.is_word("IN"):
                    state = "in_open"
                elif token.kind == "op":
                    state = "value"
                else:
                    state = "after"
            elif state == "was":
                if token.is_word("NOT"):
                    pass
                elif token.is_word("IN"):
                    state = "in_open"
                else:
                    state = "after"
            elif state == "changed":
                if token.is_word(*CHANGED_CLAUSES):
                    state, clause = "changed_value", token.text.upper()
                    used.add(clause)
                elif token.kind == "lparen":
                    state = "changed_call"
                elif token.kind == "rparen":
                    depth, state = max(0, depth - 1), "after"
                elif token.is_word("AND", "OR"):
                    state = "field"
            elif state == "changed_value":
                state = "changed"
            elif state == "changed_call":
                state = "changed"
            elif state == "is":
                state = "is_empty" if token.is_word("NOT") else "after"
            elif state == "is_empty":
                state = "after"
            elif state == "not_in":
                state = "in_open"
            elif state == "in_open":
                state = "in_list" if token.kind == "lparen" else "after"
            elif state == "in_list":
                if token.kind == "rparen":
                    state = "after"
                elif token.kind == "comma":
                    state = "in_value"
                else:
                    state = "in_next"
            elif state == "in_value":
                state = "in_next"
            elif state == "in_next":
                state = "after" if token.kind == "rparen" else "in_value"
            elif state == "value":
                state = "after"
                if token.kind == "lparen":
                    state = "value"
            elif state == "after":
                if token.kind == "rparen":
                    depth = max(0, depth - 1)
                elif token.is_word("AND", "OR"):
                    state = "field"
                elif token.kind == "lparen":
                    pass
        items = []
        if state == "field":
            items = [(FIELD_NAMES[k], FIELD_SPECS[k][4]) for k in FIELD_SPECS] + [("NOT", _("reverses the next condition"))]
        elif state == "op":
            items = [(op, "") for op in (FIELD_SPECS[field][3] if field in FIELD_SPECS else [])]
            if field in HISTORY:
                items += [("CHANGED", _("it changed at some point"))]
                if HISTORY[field][2]:
                    items += [("WAS", _("it had this value at some point")), ("WAS NOT", _("it never had this value"))]
        elif state == "was":
            items = [(self._quote(v), h) for v, h in self._value_hints(field)] + [("NOT", ""), ("IN", "")]
        elif state == "changed_value":
            if clause == "BY":
                items = [(self._quote(v), h) for v, h in self._value_hints("assignee")]
            elif clause in ("AFTER", "BEFORE"):
                items = [(self._quote(v), h) for v, h in self._value_hints("due")]
            else:
                items = [(self._quote(v), h) for v, h in self._value_hints(field)]
        elif state == "changed":
            items = [(c, h) for c, h in (
                ("FROM", _("the value before")), ("TO", _("the value after")), ("AFTER", _("on or after a date")),
                ("BEFORE", _("before a date")), ("BY", _("who changed it"))) if c not in used]
            items += [("AND", ""), ("OR", ""), ("ORDER BY", _("sort the results"))]
            if depth:
                items.append((")", ""))
        elif state in ("value", "in_value", "in_list") and field in FIELD_SPECS:
            items = [(self._quote(v), h) for v, h in self._value_hints(field)]
        elif state == "is":
            items = [("EMPTY", ""), ("NOT EMPTY", "")]
        elif state in ("not_in",):
            items = [("IN", "")]
        elif state == "in_open":
            items = [("(", "")]
        elif state in ("after", "in_next"):
            items = [("AND", ""), ("OR", ""), ("ORDER BY", _("sort the results"))]
            if state == "in_next":
                items = [(",", ""), (")", "")]
            elif depth:
                items.append((")", ""))
        matched = [i for i in items if i[0].lower().lstrip('"').startswith(prefix)] or [
            i for i in items if prefix and prefix in i[0].lower()]
        return {
            "start": start, "end": end,
            "items": [{"label": label, "insert": label, "hint": str(hint)} for label, hint in matched[:30]],
        }

    @staticmethod
    def _quote(value):
        return f'"{value}"' if re.search(r"[\s,()=~<>!]", value) else value

    def _value_hints(self, field):
        _label, _path, kind, _allowed, _hint = FIELD_SPECS[field]
        if kind == "category":
            return [(label, "") for label in CATEGORY_LABELS]
        if kind == "priority":
            return [(label, "") for label in PRIORITY_LABELS]
        if kind == "resolution":
            return [(label, "") for label in RESOLUTION_LABELS]
        if kind == "date":
            return [("today", ""), ("-7d", _("a week ago")), ("-2w", _("two weeks ago")), ("-1m", _("a month ago")),
                    ("+7d", _("in a week"))] + [(DATE_FUNCTION_NAMES[k], h) for k, h in DATE_FUNCTIONS.items()]
        if kind == "project":
            return [(self.project.name, "")]
        if kind in ("number", "text", "key", "links"):
            return []
        functions = [(name, _("a shortcut")) for name in FUNCTIONS.get(field, [])]
        return functions + [(names[0], "") for _rec, names in self._candidates(kind)]
