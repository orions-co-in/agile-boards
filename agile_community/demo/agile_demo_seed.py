"""Demo project for Agile Community. Opt-in; the add-on never creates sample data by itself.

Run in a disposable or training database (never a live one):

    odoo shell -d <database> --no-http < addons/agile_community/demo/agile_demo_seed.py

Creates the project "Demo Shop" (key SHOP, Scrum) with a four-person team, three epics, 25 issues,
a completed sprint, an active sprint, a planned sprint, a released and a planned release, a blocked
issue with a dependency, roadmap dates and two linked commits. Safe to run twice: it stops if the
project already exists. Everything goes through the normal workflow, as the administrator.
"""
from datetime import timedelta

from odoo import Command, fields

today = fields.Date.today()
admin = env.ref("base.user_admin")
env = env(user=admin)

if env["project.project"].search([("agile_key", "=", "SHOP")]):
    print("Demo Shop already exists; nothing to do.")
else:
    Users = env["res.users"].with_context(no_reset_password=True)
    team = {}
    for login, name, group in (
        ("demo_manager", "Maya Manager", "project.group_project_manager"),
        ("demo_dev", "Dev Contributor", "project.group_project_user"),
        ("demo_dev2", "Sam Contributor", "project.group_project_user"),
        ("demo_reviewer", "Riley Reviewer", "agile_community.group_agile_reviewer"),
    ):
        team[login] = Users.search([("login", "=", login)]) or Users.create({
            "name": name, "login": login, "email": f"{login}@example.com", "group_ids": [Command.link(env.ref(group).id)],
        })

    project = env["project.project"].create({
        "name": "Demo Shop", "privacy_visibility": "employees", "user_id": admin.id,
        "agile_enabled": True, "agile_key": "SHOP", "agile_method": "scrum",
    })
    # Global Project Managers are not made Agile managers automatically, so set every role explicitly.
    for login, role in (("demo_manager", "manager"), ("demo_dev", "contributor"), ("demo_dev2", "contributor"), ("demo_reviewer", "reviewer")):
        member = env["agile.project.member"].search([("project_id", "=", project.id), ("user_id", "=", team[login].id)])
        if member:
            member.write({"role": role})
        else:
            env["agile.project.member"].create({"project_id": project.id, "user_id": team[login].id, "role": role})
    Task = env["project.task"]
    kind = {n: env.ref(f"agile_community.agile_task_type_{n}") for n in ("epic", "story", "task", "bug")}
    dev, dev2 = team["demo_dev"], team["demo_dev2"]

    def epic(name, start, end):
        return Task.create({
            "name": name, "project_id": project.id, "description": f"<p>{name}</p>", "agile_task_type_id": kind["epic"].id,
            "agile_planned_start": today + timedelta(days=start), "agile_planned_end": today + timedelta(days=end),
        })

    def issue(name, type_name, points, epic_record=None, who=None):
        return Task.create({
            "name": name, "project_id": project.id, "description": f"<p>{name}. Acceptance: it works as described.</p>",
            "agile_task_type_id": kind[type_name].id, "parent_id": epic_record.id if epic_record else False,
            "story_points": points, "user_ids": [Command.set(who.ids)] if who else [Command.clear()],
        })

    def move(tasks, depth):
        steps = {
            "ready": ["action_agile_mark_ready"],
            "progress": ["action_agile_mark_ready", "action_agile_start"],
            "review": ["action_agile_mark_ready", "action_agile_start", "action_agile_send_review"],
            "done": ["action_agile_mark_ready", "action_agile_start", "action_agile_send_review", "action_agile_complete"],
        }[depth]
        for task in tasks:
            for step in steps:
                getattr(task, step)()

    checkout = epic("Checkout", -28, 20)
    search = epic("Search", -10, 35)
    mobile = epic("Mobile app", 20, 70)

    # Sprint 1: finished two weeks ago, shipped in release 1.0.
    s1_issues = [
        issue("Cart page shows totals", "story", 3, checkout, dev),
        issue("Card payment form", "story", 5, checkout, dev2),
        issue("Fix rounding on discounts", "bug", 2, checkout, dev),
        issue("Order confirmation email", "task", 2, checkout, dev2),
        issue("Product search box", "story", 5, search, dev),
    ]
    sprint1 = env["project.sprint"].create({
        "name": "Sprint 1", "project_id": project.id, "date_start": today - timedelta(days=28), "date_end": today - timedelta(days=15),
    })
    release1 = env["project.version"].create({"name": "1.0", "project_id": project.id, "release_date": today - timedelta(days=14)})
    for task in s1_issues:
        task.write({"sprint_id": sprint1.id, "version_id": release1.id})
    sprint1.action_confirm_plan()
    sprint1.action_start()
    move(s1_issues, "done")
    sprint1.action_done()
    release1.action_release()

    # Sprint 2: active, one issue in each status.
    release2 = env["project.version"].create({"name": "1.1", "project_id": project.id, "release_date": today + timedelta(days=20)})
    s2 = {
        "done": [issue("Search filters by category", "story", 5, search, dev), issue("Spelling suggestions", "task", 3, search, dev2)],
        "review": [issue("Saved addresses at checkout", "story", 5, checkout, dev2)],
        "progress": [issue("Coupon codes", "story", 8, checkout, dev), issue("Slow search on large catalogue", "bug", 3, search, dev2)],
        "ready": [issue("Search result paging", "task", 2, search, dev)],
        "backlog": [issue("Empty-cart illustration", "task", 1, checkout)],
    }
    sprint2 = env["project.sprint"].create({
        "name": "Sprint 2", "project_id": project.id, "date_start": today - timedelta(days=7), "date_end": today + timedelta(days=6),
    })
    for depth, tasks in s2.items():
        for task in tasks:
            task.write({"sprint_id": sprint2.id, "version_id": release2.id})
    sprint2.action_confirm_plan()
    sprint2.action_start()
    for depth, tasks in s2.items():
        if depth != "backlog":
            move(tasks, depth)

    # Sprint 3: planned.
    sprint3 = env["project.sprint"].create({
        "name": "Sprint 3", "project_id": project.id, "date_start": today + timedelta(days=7), "date_end": today + timedelta(days=20),
    })
    planned = [issue("Wish list", "story", 5, mobile, dev), issue("Push notifications for orders", "story", 8, mobile, dev2),
               issue("Dark theme for the app", "task", 3, mobile)]
    for task in planned:
        task.write({"sprint_id": sprint3.id})

    # Backlog: ranked, some unestimated.
    backlog = [
        issue("Guest checkout", "story", 8, checkout), issue("Apple Pay and Google Pay", "story", 13, checkout),
        issue("Product reviews", "story", 8, search), issue("Barcode scan in the app", "story", 5, mobile),
        issue("Accessibility audit of checkout", "task", 5), issue("Update product photos", "task", 0),
        issue("Crash when the cart is empty on iOS", "bug", 3, mobile), issue("Invoice PDF layout", "bug", 2, checkout),
        issue("Gift cards", "story", 0, checkout), issue("Offline mode", "story", 0, mobile),
    ]

    # A blocked issue and a dependency for the roadmap.
    blocked = s2["progress"][0]
    blocked.write({"depend_on_ids": [Command.link(s2["review"][0].id)]})
    blocked.write({"agile_blocked": True, "agile_block_reason": "Waiting for the payment provider's sandbox key"})

    # Planned dates on the issues that carry the roadmap.
    for task, start, end in ((s2["progress"][0], -5, 8), (s2["review"][0], -6, 2), (planned[0], 8, 18)):
        task.write({"agile_planned_start": today + timedelta(days=start), "agile_planned_end": today + timedelta(days=end)})

    # Two linked commits on the development tab.
    for task, sha, title in ((s2["progress"][0], "a1b2c3d4", f"{s2['progress'][0].issue_key} validate coupon codes"),
                             (s2["review"][0], "e5f6a7b8", f"{s2['review'][0].issue_key} store addresses")):
        if "agile.git.event" not in env:
            continue  # the Development tab needs agile_pro
        env["agile.git.event"].sudo().create({
            "task_id": task.id, "provider": "github", "kind": "commit", "ref": sha * 5, "title": title,
            "author": "Dev Contributor", "branch": "main", "state": "committed", "event_date": fields.Datetime.now(),
        })

    env["agile.metric.snapshot"].sudo()._cron_capture_daily_snapshots()
    if not env.context.get("agile_demo_no_commit"):  # set by the automated test
        env.cr.commit()
    print("Demo Shop ready:", Task.search_count([("project_id", "=", project.id)]), "issues; sign in as",
          ", ".join(team), "(set a password from Settings > Users)")
