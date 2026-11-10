# Copyright 2016 ACSONE SA/NV (<http://acsone.eu>)
# Copyright 2024 Tecnativa - Carlos Lopez
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

{
    "name": "Web timeline",
    "summary": "Interactive visualization chart to show events in time",
    "version": "20.0.1.0.0",
    "development_status": "Production/Stable",
    "author": "ACSONE SA/NV, "
    "Tecnativa, "
    "Monk Software, "
    "Onestein, "
    "Trobz, "
    "Odoo Community Association (OCA)",
    "category": "web",
    "license": "AGPL-3",
    "website": "https://github.com/OCA/web",
    "depends": ["web"],
    "data": [],
    "demo": ["demo/ir_cron_view.xml"],
    "application": False,
    "installable": True,
    "assets": {
        "web.assets_backend": [
            "agile_timeline/static/src/views/timeline/timeline_view.scss",
            "agile_timeline/static/src/views/timeline/timeline_canvas.scss",
            "agile_timeline/static/src/views/timeline/timeline_arch_parser.esm.js",
            "agile_timeline/static/src/views/timeline/timeline_view.esm.js",
            "agile_timeline/static/src/views/timeline/timeline_renderer.esm.js",
            "agile_timeline/static/src/views/timeline/timeline_renderer.xml",
            "agile_timeline/static/src/views/timeline/timeline_controller.esm.js",
            "agile_timeline/static/src/views/timeline/timeline_controller.xml",
            "agile_timeline/static/src/views/timeline/timeline_model.esm.js",
            "agile_timeline/static/src/views/timeline/timeline_canvas.esm.js",
        ],
        "agile_timeline.vis-timeline_lib": [
            "/agile_timeline/static/lib/vis-timeline/vis-timeline-graph2d.js",
            "/agile_timeline/static/lib/vis-timeline/vis-timeline-graph2d.css",
        ],
        "web.qunit_suite_tests": [
            "agile_timeline/static/tests/helpers.esm.js",
            "agile_timeline/static/tests/web_timeline_arch_parser_tests.esm.js",
            "agile_timeline/static/tests/web_timeline_view_tests.esm.js",
        ],
    },
}
