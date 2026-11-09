def migrate(cr, version):
    """AI agents are off everywhere after the upgrade (Q-1202): the company and project switches start false."""
    cr.execute("ALTER TABLE project_project ADD COLUMN IF NOT EXISTS agile_agent_enabled boolean")
    cr.execute("UPDATE project_project SET agile_agent_enabled = FALSE WHERE agile_agent_enabled IS NULL")
    cr.execute("ALTER TABLE res_company ADD COLUMN IF NOT EXISTS agile_agent_enabled boolean")
    cr.execute("UPDATE res_company SET agile_agent_enabled = FALSE WHERE agile_agent_enabled IS NULL")
