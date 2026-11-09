{
    "name": "Agile Boards Timesheets",
    "summary": "Time logged on an Agile issue comes from its timesheets",
    "version": "19.0.1.0.0",
    "category": "Services/Project",
    "author": "Orions",
    "license": "AGPL-3",
    "depends": ["agile_community", "hr_timesheet"],
    "data": [
        "security/ir.model.access.csv",
        "views/log_work_views.xml",
    ],
    "auto_install": True,
    "installable": True,
}
