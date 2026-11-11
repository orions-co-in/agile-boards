# Third-party notices

Agile Boards (`agile_community`) and Agile Boards Pro (`agile_pro`) are licensed under AGPL-3, see `LICENSE`.

`agile_community` depends on three add-ons that are shipped next to it in the same repository. They are based on
modules of the Odoo Community Association (OCA), keep their original AGPL-3 license and their original authors,
and their manifests, README files and translations carry that attribution:

| Add-on here | Based on (OCA) | License | Authors (see each manifest) |
| --- | --- | --- | --- |
| `agile_scrum` | `project_scrum` (OCA/project-agile) | AGPL-3 | Binhex, Odoo Community Association (OCA) |
| `agile_version` | `project_version` (OCA/project) | AGPL-3 | Lansana Barry Sow, APSL-Nagarro, Odoo Community Association (OCA) |
| `agile_timeline` | `web_timeline` (OCA/web) | AGPL-3 | ACSONE SA/NV, Tecnativa and others, Odoo Community Association (OCA) |

Orions added features and changes on top of these modules (for example sprint planning and capacity in `agile_scrum`
and quarter mode in `agile_timeline`). Those additions are released under the same AGPL-3 license.

`agile_timeline` also bundles the vis-timeline library (version 7.7.3, https://visjs.github.io/vis-timeline/) in
`static/lib/vis-timeline/`. vis-timeline is available under the Apache License 2.0 or the MIT License; its license
notice is kept in the file header.
