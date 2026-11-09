import re

from lxml import etree

from odoo.tests.common import TransactionCase
from odoo.tools import file_open

LABEL_ATTRS = (
    "aria-label", "aria-labelledby", "title", "t-att-aria-label", "t-attf-aria-label",
    "t-att-title", "t-attf-title", "t-att-aria-labelledby",
)
TEXT_ATTRS = ("t-out", "t-esc", "t-call")
TEMPLATES = [
    "backlog/agile_backlog_list.xml", "backlog/agile_move_dialog.xml", "backlog/agile_row_sheet.xml",
    "board/agile_board_bar.xml", "board/agile_board_renderer.xml", "components/pulse/agile_pulse.xml",
    "filter/agile_query_field.xml", "reports/agile_reports.xml", "reports/agile_burndown.xml",
    "reports/agile_cfd.xml", "roadmap/agile_roadmap.xml",
]


def _luminance(color):
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _ratio(first, second):
    light, dark = sorted([_luminance(first), _luminance(second)], reverse=True)
    return (light + 0.05) / (dark + 0.05)


def _tokens():
    """The light and dark --ag-* colour tokens of agile_tokens.scss."""
    with file_open("agile_community/static/src/scss/agile_tokens.scss") as handle:
        text = handle.read()
    root = text.split(":root {", 1)[1].split("\n}", 1)[0]
    dark = text.split("[data-bs-theme=\"dark\"] {", 1)[1].split("\n}", 1)[0]
    def pick(block):
        colours = {}
        for name, value in re.findall(r"--ag-([a-z0-9-]+):\s*(#[0-9a-fA-F]{3,6});", block):
            if len(value) == 4:  # #fff
                value = "#" + "".join(c * 2 for c in value[1:])
            colours[name] = value
        return colours

    light = pick(root)
    return light, {**light, **pick(dark)}


class TestAgileAccessibility(TransactionCase):
    """H-602: static checks that keep the Agile screens readable and operable without a pointer."""

    TEXT_TOKENS = ["ink", "muted", "plum", "amber-text", "red", "focus", "teal",
                   "s-backlog", "s-ready", "s-progress", "s-review", "s-done", "s-canceled",
                   "t-epic", "t-story", "t-task", "t-bug"]

    def test_text_colours_keep_aa_contrast_on_both_surfaces_in_both_themes(self):
        light, dark = _tokens()
        for theme, tokens in (("light", light), ("dark", dark)):
            for surface in ("surface", "paper"):
                for name in self.TEXT_TOKENS:
                    ratio = _ratio(tokens[name], tokens[surface])
                    self.assertGreaterEqual(
                        ratio, 4.5, f"{theme}: --ag-{name} {tokens[name]} on {surface} is {ratio:.2f}:1"
                    )

    def test_focus_ring_is_visible_in_both_themes(self):
        for tokens in _tokens():
            for surface in ("surface", "paper"):
                self.assertGreaterEqual(_ratio(tokens["focus"], tokens[surface]), 3.0)

    def test_no_stylesheet_hard_codes_the_focus_outline_colour(self):
        for path in ("scss/agile_accessibility.scss", "workflow/agile_workflow_diagram.scss"):
            with file_open(f"agile_community/static/src/{path}") as handle:
                for line in handle:
                    if "outline" in line and "solid" in line:
                        self.assertIn("var(--ag-focus", line, f"{path}: {line.strip()}")

    def test_templates_name_every_button_field_image_and_chart(self):
        problems = []
        for template in TEMPLATES:
            with file_open(f"agile_community/static/src/{template}", "rb") as handle:
                tree = etree.parse(handle)
            for el in tree.iter():
                if not isinstance(el.tag, str):
                    continue
                where = f"{template}:{el.sourceline} <{el.tag}>"
                named = any(a in el.attrib for a in LABEL_ATTRS)
                text = "".join(el.itertext()).strip() or any(a in el.attrib for a in TEXT_ATTRS) or el.xpath(
                    ".//*[@t-out or @t-esc or @t-call]"
                )
                if el.tag == "button" and not (text or named):
                    problems.append(f"{where} has no name")
                if el.tag in ("input", "select", "textarea") and el.get("type") != "hidden" and not (
                    named or el.xpath("ancestor::label") or "id" in el.attrib
                ):
                    problems.append(f"{where} has no label")
                if el.tag == "img" and not any(a in el.attrib for a in ("alt", "t-att-alt", "t-attf-alt")):
                    problems.append(f"{where} has no alt text")
                if el.tag.endswith("svg") and not (
                    named or "role" in el.attrib or "aria-hidden" in el.attrib or el.xpath("ancestor::*[@aria-hidden or @role]")
                ):
                    problems.append(f"{where} has no role or label")
        self.assertEqual(problems, [])

    def test_roadmap_bars_move_with_the_arrow_keys(self):
        with file_open("agile_community/static/src/roadmap/agile_roadmap.xml") as handle:
            text = handle.read()
        self.assertIn('t-on-keydown="onBarKeydown"', text)
