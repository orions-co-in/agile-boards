"""Agile Free / Pro split: hand the Pro models and fields to agile_pro without dropping their tables.

Odoo deletes the models, fields, constraints and relation tables whose external ids belong to a module but are no
longer loaded by it, and deleting a model or a field drops its table or column. The Pro features moved to agile_pro,
so their external ids are re-pointed here before the update runs. Views, actions, menus, crons, access rows and rules
are not re-pointed: Odoo removes the old ones and agile_pro creates its own when it is installed.
Installed without agile_pro, the tables and columns stay dormant with their data.
"""

# Models that moved as a whole (their fields, constraints and selection values move with them).
MOVED_MODELS = [
    "agile.agent.api",
    "agile.agent.call",
    "agile.agent.create",
    "agile.agent.key",
    "agile.agent.key.show",
    "agile.agent.token",
    "agile.ai",
    "agile.ai.result",
    "agile.ai.usage",
    "agile.audit",
    "agile.automation.fired",
    "agile.automation.library",
    "agile.automation.rule",
    "agile.automation.run",
    "agile.automation.test",
    "agile.capacity",
    "agile.chat.link",
    "agile.chat.pending",
    "agile.classification",
    "agile.custom.choice",
    "agile.custom.field",
    "agile.custom.field.add",
    "agile.custom.value",
    "agile.dashboard",
    "agile.dashboard.tile",
    "agile.deployment",
    "agile.digest.event",
    "agile.digest.preference",
    "agile.git.event",
    "agile.hook.delivery",
    "agile.move.approval",
    "agile.move.approval.reject",
    "agile.plan.item",
    "agile.plan.scenario",
    "agile.plan.scenario.line",
    "agile.secret.show",
    "agile.security.level",
    "agile.signal",
    "agile.vulnerability",
    "agile.vulnerability.link",
    "agile_community.jira_import_wizard",
]

# Fields agile_pro now adds to models that stay in agile_community, or to Odoo's own models.
MOVED_FIELDS = {
    "agile.workflow.transition": [
        "action_ids",
        "approval_mode",
        "approver_ids",
        "required_custom_field_ids",
    ],
    "project.project": [
        "agile_agent_company_enabled",
        "agile_agent_enabled",
        "agile_ai_company_enabled",
        "agile_ai_enabled",
        "agile_automation_rule_ids",
        "agile_chat_enabled",
        "agile_chat_secret",
        "agile_chat_slack_url",
        "agile_chat_teams_url",
        "agile_classification_id",
        "agile_classification_warning",
        "agile_custom_field_ids",
        "agile_git_base_branch",
        "agile_git_bitbucket_url",
        "agile_git_enabled",
        "agile_git_gitlab_url",
        "agile_git_repo_provider",
        "agile_git_repo_url",
        "agile_git_secret",
        "agile_git_smart_commits",
        "agile_git_webhook_url",
        "agile_hook_comments",
        "agile_hook_created",
        "agile_hook_delivery_count",
        "agile_hook_enabled",
        "agile_hook_format",
        "agile_hook_status",
        "agile_hook_url",
        "agile_security_level_ids",
        "agile_signal_enabled",
        "agile_signal_secret",
        "agile_signal_url",
        "agile_vulnerability_open_count",
    ],
    "project.task": [
        "agile_ai_available",
        "agile_approval_ids",
        "agile_approval_text",
        "agile_branch_command",
        "agile_branch_name",
        "agile_branch_ready",
        "agile_branch_url",
        "agile_can_decide_approval",
        "agile_classification_effective_id",
        "agile_classification_id",
        "agile_classification_name",
        "agile_classification_tone",
        "agile_classification_warning",
        "agile_custom_card_text",
        "agile_custom_summary",
        "agile_custom_value_ids",
        "agile_dev_summary",
        "agile_git_event_count",
        "agile_git_event_ids",
        "agile_jira_key",
        "agile_pending_approval_id",
        "agile_plan_item_id",
        "agile_security_level_id",
        "agile_shown_custom_value_ids",
        "agile_signal_count",
        "agile_signal_ids",
        "agile_unfilled_custom_count",
        "agile_visible_custom_value_ids",
        "agile_vulnerability_count",
        "agile_vulnerability_ids",
    ],
    "res.company": [
        "agile_agent_enabled",
        "agile_ai_enabled",
        "agile_ai_include_restricted",
        "agile_ai_model",
        "agile_ai_url",
    ],
    "res.config.settings": [
        "agile_agent_enabled",
        "agile_ai_enabled",
        "agile_ai_include_restricted",
        "agile_ai_key",
        "agile_ai_model",
        "agile_ai_url",
    ],
    "res.users": [
        "agile_agent_calls_24h",
        "agile_agent_creator_id",
        "agile_agent_last_call",
        "agile_agent_level",
        "agile_agent_projects",
    ],
}

# Many2many tables of the moved fields.
MOVED_RELATIONS = [
    "agile_automation_rule_notify_rel",
    "agile_automation_rule_task_type_rel",
    "agile_custom_field_type_rel",
    "agile_custom_value_choice_rel",
    "agile_custom_value_user_rel",
    "agile_dashboard_share_rel",
    "agile_move_approval_approver_rel",
    "agile_move_approval_done_rel",
    "agile_security_level_user_rel",
    "agile_transition_approver_rel",
    "agile_workflow_transition_custom_rel",
]

# Buttons the Pro features add to forms; a view that still names one cannot be validated without agile_pro.
MOVED_BUTTONS = [
    "action_add",
    "action_add_comment",
    "action_agile_add_custom_field",
    "action_agile_ai_suggest",
    "action_agile_ai_summarise",
    "action_agile_approve",
    "action_agile_hook_test",
    "action_agile_reject",
    "action_apply_priority",
    "action_apply_type",
    "action_apply_user",
    "action_approve",
    "action_check",
    "action_create",
    "action_create_issue",
    "action_dismiss",
    "action_download_agile_audit",
    "action_generate_agile_git_secret",
    "action_generate_agile_signal_secret",
    "action_link",
    "action_link_issue",
    "action_make_key",
    "action_manage_agile_custom_fields",
    "action_manage_agile_security_levels",
    "action_new_guided",
    "action_open_agile_audit",
    "action_open_agile_automation",
    "action_open_agile_capacity_page",
    "action_open_agile_jira_import",
    "action_open_agile_my_notifications",
    "action_open_agile_other_import",
    "action_open_classic",
    "action_open_library",
    "action_open_reject",
    "action_open_rule_runs",
    "action_open_runs",
    "action_open_test",
    "action_reject",
    "action_run",
    "action_unlink_issue",
    "action_view_agile_hook_deliveries",
    "action_view_agile_vulnerabilities",
]

# Data rows that came with the Pro features (agile.classification keeps the people's edits and their links).
MOVED_DATA_MODELS = ["agile.classification"]


def _key(model):
    return model.replace(".", "_")


def _like(prefix):
    """A LIKE pattern for names that start with the prefix, with its underscores taken literally."""
    escape = chr(92)
    return prefix.replace(escape, escape * 2).replace("_", escape + "_") + "%"


def _repoint(cr, where, params):
    cr.execute(
        """UPDATE ir_model_data SET module = 'agile_pro'
            WHERE module = 'agile_community' AND ({where})
              AND NOT EXISTS (SELECT 1 FROM ir_model_data o WHERE o.module = 'agile_pro'
                               AND o.name = ir_model_data.name AND o.model = ir_model_data.model)""".format(where=where),
        params,
    )


PARAM = "agile_community.split_deactivated_views"


def _deactivate_views(cr):
    """Switch off the old views that mention a moved model, field or button.

    The update validates each view it loads against the models of the modules that are loaded. Until Odoo has
    removed the old Pro views at the end of the update they would break every form they extend. The post-migration
    switches on again the ones that stay in agile_community (their XML is reloaded without the Pro parts).
    """
    tokens = set(MOVED_BUTTONS) | set(MOVED_MODELS)
    for names in MOVED_FIELDS.values():
        tokens |= set(names)
    cr.execute(
        """SELECT v.id FROM ir_ui_view v
             JOIN ir_model_data d ON d.model = 'ir.ui.view' AND d.res_id = v.id AND d.module = 'agile_community'
            WHERE v.active AND v.arch_db::text LIKE ANY(%s)""",
        (["%" + t + "%" for t in sorted(tokens)],),
    )
    ids = [row[0] for row in cr.fetchall()]
    if ids:
        cr.execute("UPDATE ir_ui_view SET active = false WHERE id = ANY(%s)", (ids,))
    cr.execute(
        """INSERT INTO ir_config_parameter (key, value, create_date, write_date)
           VALUES (%s, %s, now(), now())
           ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
        (PARAM, ",".join(str(i) for i in ids)),
    )


def migrate(cr, version):
    if not version:
        return
    _deactivate_views(cr)
    for model in MOVED_MODELS:
        key = _key(model)
        _repoint(
            cr,
            """(model = 'ir.model' AND name = %(model)s)
               OR (model = 'ir.model.fields' AND name LIKE %(fields)s)
               OR (model = 'ir.model.fields.selection' AND name LIKE %(selection)s)
               OR (model = 'ir.model.constraint' AND name LIKE %(constraints)s)""",
            {
                "model": "model_" + key,
                "fields": _like("field_" + key + "__"),
                "selection": _like("selection__" + key + "__"),
                "constraints": _like("constraint_" + key + "_"),
            },
        )
    for model, names in MOVED_FIELDS.items():
        key = _key(model)
        _repoint(
            cr,
            """(model = 'ir.model.fields' AND name = ANY(%(fields)s))
               OR (model = 'ir.model.fields.selection' AND name LIKE ANY(%(selection)s))""",
            {
                "fields": ["field_" + key + "__" + n for n in names],
                "selection": [_like("selection__" + key + "__" + n + "__") for n in names],
            },
        )
    _repoint(cr, "model = 'ir.model.relation' AND name = ANY(%(tables)s)",
             {"tables": ["table_" + t for t in MOVED_RELATIONS]})
    _repoint(cr, "model = ANY(%(models)s)", {"models": MOVED_DATA_MODELS})
