Odoo Community Association (OCA) upstream source
=================================================

This Odoo 19 module is selectively migrated from the OCA `agile_scrum`
add-on at OCA/project-agile commit
`ef587cd4d3f4eec4766ed39aed7bd69ecb189ffc` (PR #46), based on its Odoo 18
implementation and the OCA/project 18.0 migration PR #1509. It retains the
upstream module name, author attribution, AGPL-3 license, documentation, and
tests.

Odoo 19 and product-specific adaptations:

* depends on native `project`; the optional timeline dependency and views are
  omitted from the core sprint flow;
* Scrum can be enabled per project, sprints cannot be global or cross-project,
  and project task assignment is checked server-side;
* only planned-to-active-to-completed transitions are accepted, one active
  sprint per project is enforced in PostgreSQL, and active sprint scope and
  planning fields are protected from accidental edits;
* completion requires every unfinished issue to be moved to backlog or another
  planned sprint first; automatic date-based state changes and silent task
  reassignment/assignee clearing are removed;
* the generated add-on description omits the encoding declaration that causes
  Odoo 19's Apps UI install path to fail in the affected lxml code path.

Story points, capacity, commitment snapshots, scope-change reasons, and the
completion destination dialog remain product work tracked in the Agile
feature checklist.
