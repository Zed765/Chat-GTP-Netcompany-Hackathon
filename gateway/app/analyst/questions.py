"""The questions the Ask page suggests. Each is paired with SQL that answers it: the pairs are
the worked examples in the prompt the model writes its SQL from. Nothing here is run."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Example:
    question: str
    sql: str


EXAMPLES: tuple[Example, ...] = (
    Example(
        question="Which teams sent client data to unapproved AI tools this week?",
        sql="""
            SELECT team,
                   coalesce(tool_name, tool) AS tool,
                   count(*) AS prompts,
                   count(*) FILTER (WHERE sent_unmasked) AS sent_unmasked
            FROM v_events
            WHERE channel = 'prompt'
              AND 'CLIENT' = ANY(data_types)
              AND tool_status = 'unapproved'
              AND ts >= now() - interval '7 days'
            GROUP BY team, coalesce(tool_name, tool)
            ORDER BY prompts DESC, team
        """,
    ),
    Example(
        question="Which kinds of sensitive data appear most often in prompts?",
        sql="""
            SELECT data_type, count(*) AS prompts, count(DISTINCT team) AS teams
            FROM v_events, unnest(data_types) AS data_type
            WHERE channel = 'prompt' AND ts >= now() - interval '14 days'
            GROUP BY data_type
            ORDER BY prompts DESC
        """,
    ),
    Example(
        question="Which unapproved AI tools are used most, and by how many teams?",
        sql="""
            SELECT name AS tool, requests_14d AS requests, teams_14d AS teams, risk_score
            FROM v_tools
            WHERE status IN ('unapproved', 'unknown') AND requests_14d > 0
            ORDER BY requests_14d DESC
        """,
    ),
    Example(
        question="How has the share of prompts with sensitive data changed over 14 days?",
        sql="""
            SELECT day,
                   count(*) AS prompts,
                   count(*) FILTER (WHERE sensitive) AS sensitive,
                   round(100.0 * count(*) FILTER (WHERE sensitive) / count(*), 1) AS sensitive_pct,
                   count(*) FILTER (WHERE sensitive AND sent_unmasked) AS sent_unmasked
            FROM v_events
            WHERE channel = 'prompt' AND ts >= now() - interval '14 days'
            GROUP BY day
            ORDER BY day
        """,
    ),
    Example(
        question="Which teams trigger the most blocks and warnings?",
        sql="""
            SELECT team, blocked_14d + warned_14d AS blocks_and_warnings,
                   blocked_14d AS blocked, warned_14d AS warned, events_14d AS events
            FROM v_teams
            ORDER BY blocks_and_warnings DESC, team
        """,
    ),
    Example(
        question="Which newly discovered AI tools are waiting for review?",
        sql="""
            SELECT name AS tool, category, risk_score, requests_14d AS requests, first_seen
            FROM v_tools
            WHERE needs_review
            ORDER BY requests_14d DESC, name
        """,
    ),
)
