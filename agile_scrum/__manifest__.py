# Copyright 2024 Binhex - Adasat Torres de León (https://www.binhex.cloud)
# Copyright 2026 Odoo Community Association (OCA)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

{
    "name": "Agile Scrum",
    "version": "20.0.1.6.0",
    "category": "Project",
    "website": "https://github.com/OCA/project-agile",
    "author": "Binhex, Odoo Community Association (OCA)",
    "license": "AGPL-3",
    "installable": True,
    "application": False,
    "summary": "Sprints for Agile Boards: plan, start and complete sprints in Odoo Project",
    "depends": ["project"],
    "data": [
        "wizard/project_sprint_wizard_views.xml",
        "wizard/project_sprint_correction_views.xml",
        "views/project_sprint_views.xml",
        "views/project_task_views.xml",
        "views/project_views.xml",
        'security/ir.access.csv',
    ],
    "maintainers": ["adasatorres"],
}
