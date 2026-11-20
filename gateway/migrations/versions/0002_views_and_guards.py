"""analyst views, read-only role and audit log guard"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

READONLY_ROLE = "aspida_readonly"
SMALL_TEAM_USERS = 3

# Views for the analyst chat. They carry no user pseudonym, conversation or snippet, and
# fold any team with fewer than three active users in the last 30 days into "Other".
# `sent_unmasked` is true when the text reached the AI tool as written: the gateway allowed
# it, or the prompt was only seen in an activity log.
V_EVENTS = f"""
CREATE VIEW v_events AS
WITH small_teams AS (
    SELECT team FROM events
    WHERE ts >= now() - interval '30 days'
    GROUP BY team
    HAVING count(DISTINCT user_pseudonym) < {SMALL_TEAM_USERS}
)
SELECT e.id,
       e.ts,
       (e.ts AT TIME ZONE 'UTC')::date AS day,
       CASE WHEN e.team IN (SELECT team FROM small_teams) THEN 'Other' ELSE e.team END AS team,
       e.tool,
       t.name AS tool_name,
       t.category AS tool_category,
       e.tool_status,
       e.channel,
       e.action,
       e.rule,
       e.policy_version,
       e.data_types,
       cardinality(e.data_types) > 0 AS sensitive,
       e.agent_tool,
       e.tainted,
       e.origin,
       e.forwarded,
       e.forwarded AND (e.origin = 'log' OR e.action = 'allow') AS sent_unmasked
FROM events e
LEFT JOIN tools t ON t.slug = e.tool
"""

V_TOOLS = """
CREATE VIEW v_tools AS
SELECT t.slug AS tool,
       t.name,
       t.category,
       t.status,
       t.risk_score,
       t.rating_source,
       t.needs_review,
       t.first_seen,
       t.last_seen,
       coalesce(u.requests, 0) AS requests_14d,
       coalesce(u.teams, 0) AS teams_14d
FROM tools t
LEFT JOIN (
    SELECT tool_id, sum(requests) AS requests, count(DISTINCT team) AS teams
    FROM tool_usage
    WHERE day >= current_date - 13
    GROUP BY tool_id
) u ON u.tool_id = t.id
"""

V_TEAMS = """
CREATE VIEW v_teams AS
SELECT team,
       count(*) AS events_14d,
       count(*) FILTER (WHERE sensitive) AS sensitive_events_14d,
       count(*) FILTER (WHERE action = 'block') AS blocked_14d,
       count(*) FILTER (WHERE action = 'redact') AS redacted_14d,
       count(*) FILTER (WHERE action = 'warn') AS warned_14d,
       count(*) FILTER (WHERE sensitive AND sent_unmasked) AS sent_unmasked_14d,
       count(*) FILTER (WHERE tool_status IN ('unapproved', 'unknown'))
           AS unapproved_tool_events_14d,
       count(DISTINCT tool) AS tools_used_14d
FROM v_events
WHERE ts >= now() - interval '14 days'
GROUP BY team
"""

AUDIT_GUARD = """
CREATE FUNCTION audit_log_is_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only';
END
$$ LANGUAGE plpgsql
"""


def upgrade() -> None:
    for view in (V_EVENTS, V_TOOLS, V_TEAMS):
        op.execute(view)
    op.execute(
        f"""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{READONLY_ROLE}') THEN
                CREATE ROLE {READONLY_ROLE} NOLOGIN;
            END IF;
        END $$
        """
    )
    op.execute(f"GRANT SELECT ON v_events, v_tools, v_teams TO {READONLY_ROLE}")
    op.execute(AUDIT_GUARD)
    op.execute(
        "CREATE TRIGGER audit_log_no_change BEFORE UPDATE OR DELETE ON audit_log "
        "FOR EACH ROW EXECUTE FUNCTION audit_log_is_append_only()"
    )
    op.execute(
        "CREATE TRIGGER audit_log_no_truncate BEFORE TRUNCATE ON audit_log "
        "EXECUTE FUNCTION audit_log_is_append_only()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER audit_log_no_truncate ON audit_log")
    op.execute("DROP TRIGGER audit_log_no_change ON audit_log")
    op.execute("DROP FUNCTION audit_log_is_append_only")
    for view in ("v_teams", "v_tools", "v_events"):
        op.execute(f"DROP VIEW {view}")
