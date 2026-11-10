# Agile Boards for Odoo 20.0

Scrum and Kanban boards, backlog, sprints, releases and reports inside Odoo's own **Project** app. Agile Boards (technical name `agile_community`) is free and open source (AGPL-3). It works with Odoo 20.0 Community; there is no separate server and no data leaves your Odoo.

The paid add-on [Agile Boards Connect](https://github.com/orions-co-in/agile-boards-connect) adds Git links, chat, AI and agent tools, automation, approvals, capacity planning and more. Agile Boards works fully without it.

## What you get

| Area | Features |
| --- | --- |
| Issues | Issue types, issue keys (for example SHOP-12), sub-issues, epics, links (blocks, relates to, duplicates), labels, components, estimates in points, hours or counts, restricted issues |
| Planning | Backlog with drag-and-drop and keyboard ranking, sprints (plan, confirm, start, complete with carry-over), Move to menu, bulk edit, clone, move to another project |
| Boards | Scrum and Kanban boards, swimlanes, WIP limits, merged columns, several boards per project, saved views, quick filters, compact cards, phone layout |
| Workflow | Statuses, allowed moves, resolution on close, workflow templates, a visual workflow editor |
| Releases | Releases and versions, components, release notes and readiness |
| Insight | Summary with sprint pulse, burndown, burnup, cumulative flow, control chart, velocity, sprint report, board insights, saved filters with a search language |
| Roadmap | Epic and release timeline with dependencies and blockers, shareable link, export |
| People | Project roles (manager, contributor, reviewer, stakeholder), permission schemes, My Work, notifications, mail to issue, optional timesheet bridge |

Everything respects Odoo's own Project access: nobody sees an Agile project they cannot already open in Project.

## Requirements

- Odoo 20.0 Community (or Enterprise) with the **Project** app (`project`). The `hr_timesheet` app is only needed for the optional bridge `agile_community_timesheet`.
- The other modules in this repository: `project_scrum`, `project_version`, `web_timeline` (installed automatically as dependencies).

## Install

1. Clone this repository branch into your add-ons folder, or add it to your `addons_path`:

   ```bash
   git clone --branch 20.0 https://github.com/orions-co-in/agile-boards.git /path/to/addons/agile-boards
   ```

2. Restart Odoo, open **Apps**, press **Update Apps List**, search for **Agile Boards** and press **Install**.
   Or from the command line: `odoo -d <database> -i agile_community --stop-after-init`.
3. Open **Project**, open or create a project, switch on **Agile** in its settings, choose Scrum or Kanban and give it a short key.

For a database that already has Agile Boards, update with `odoo -d <database> -u agile_community`.

## First steps

1. **Project > Projects:** open a project, tick **Agile** on the Settings tab, pick Scrum or Kanban, set the key and save.
2. **Team:** the project manager adds people with a role (manager, contributor, reviewer, stakeholder) on the project's Agile team.
3. **Backlog:** add issues, estimate them, rank them by dragging (or Alt+Arrow keys), then create a sprint and move issues into it.
4. **Board:** start the sprint and work the board. Complete the sprint when done; unfinished issues carry over.
5. **Reports and Roadmap:** the sidebar shows the sprint pulse, reports, releases and the roadmap.

## User guide

The full role-by-role guide, step-by-step walkthroughs and keyboard shortcuts are in the project's documentation:
[docs/USER_GUIDE.md](https://github.com/orions-co-in/odoo-addons/blob/apps/agile-community/19.0/agile-community/docs/USER_GUIDE.md) and the illustrated
[getting started guide](https://github.com/orions-co-in/odoo-addons/blob/apps/agile-community/19.0/agile-community/docs/guide/GETTING_STARTED.md).
Inside Odoo, press `?` on any Agile screen for the shortcut list.

## Support

Open an issue at <https://github.com/orions-co-in/agile-boards/issues> or write to support@orions.co.in. Please include your Odoo version (20.0), the module version and what you clicked.

## License

AGPL-3. See `LICENSE` in each module. Copyright Orions.
