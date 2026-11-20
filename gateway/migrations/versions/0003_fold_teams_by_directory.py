"""fold small teams by their size in the directory"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

SMALL_TEAM_USERS = 3

# Replacing the view in place keeps its columns, its grants and the view built on it.
V_EVENTS = """
CREATE OR REPLACE VIEW v_events AS
WITH {folding}
SELECT e.id,
       e.ts,
       (e.ts AT TIME ZONE 'UTC')::date AS day,
       {team} AS team,
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

# A team is named only when the directory lists at least three people in it. Every other
# team, and any team the directory does not know, is shown as "Other". Events play no part,
# so nothing written under a team's name can make a team of one visible.
BY_DIRECTORY = V_EVENTS.format(
    folding=f"""named_teams AS (
    SELECT team FROM directory_users
    GROUP BY team
    HAVING count(*) >= {SMALL_TEAM_USERS}
)""",
    team="CASE WHEN e.team IN (SELECT team FROM named_teams) THEN e.team ELSE 'Other' END",
)

BY_ACTIVITY = V_EVENTS.format(
    folding=f"""small_teams AS (
    SELECT team FROM events
    WHERE ts >= now() - interval '30 days'
    GROUP BY team
    HAVING count(DISTINCT user_pseudonym) < {SMALL_TEAM_USERS}
)""",
    team="CASE WHEN e.team IN (SELECT team FROM small_teams) THEN 'Other' ELSE e.team END",
)


def upgrade() -> None:
    op.execute(BY_DIRECTORY)


def downgrade() -> None:
    op.execute(BY_ACTIVITY)
