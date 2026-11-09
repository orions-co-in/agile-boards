# Copyright 2024 Binhex - Adasat Torres de León (https://www.binhex.cloud)
# Copyright 2026 Odoo Community Association (OCA)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

{
    "name": "Project Scrum",
    "version": "19.0.1.6.0",
    "category": "Project",
    "website": "https://github.com/OCA/project-agile",
    "author": "Binhex, Odoo Community Association (OCA)",
    "license": "AGPL-3",
    "installable": True,
    "application": False,
    "summary": "This addon allow use the scrum methodology in projects",
    "depends": ["project"],
    "data": [
        "security/project_sprint_security.xml",
        "security/ir.model.access.csv",
        "wizard/project_sprint_wizard_views.xml",
        "wizard/project_sprint_correction_views.xml",
        "views/project_sprint_views.xml",
        "views/project_task_views.xml",
        "views/project_views.xml",
    ],
    "maintainers": ["adasatorres"],
}
