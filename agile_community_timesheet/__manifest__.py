{
    "name": "Agile Boards Timesheets",
    "summary": "Time logged on an Agile issue comes from its timesheets",
    "version": "20.0.1.0.0",
    "category": "Services/Project",
    "author": "Orions",
    "license": "AGPL-3",
    "depends": ["agile_community", "hr_timesheet"],
    "data": [
        "views/log_work_views.xml",
        'security/ir.access.csv',
    ],
    "auto_install": True,
    "installable": True,
}
