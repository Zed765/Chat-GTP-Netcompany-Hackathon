"""Plain-language questions over the analyst views. The model writes the SQL, which must pass
`sql_guard` and then runs as a read-only role with a statement timeout."""

import textwrap
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from gateway.app.analyst.questions import EXAMPLES
from gateway.app.analyst.schemas import AskResult, ChartSpec
from gateway.app.analyst.sql_guard import MAX_ROWS, UnsafeSqlError, guard
from gateway.app.db.session import Database
from gateway.app.llm.client import LLM

STATEMENT_TIMEOUT = "5s"
SUMMARY_ROWS = 20

SCHEMA = """
v_events: one row per inspected prompt, tool call or tool result. Team level, no user identity.
  id, ts (timestamptz), day (date), team, tool (slug), tool_name, tool_category,
  tool_status ('approved' | 'tolerated' | 'unapproved' | 'unknown'),
  channel ('prompt' | 'tool_call' | 'tool_result'),
  action ('allow' | 'redact' | 'warn' | 'block'), rule, policy_version,
  data_types (text[]; for example CLIENT, PERSON, AFM, IBAN, EMAIL, PHONE, SECRET, CONTRACT,
              FINANCIAL, HR, HEALTH, SOURCE_CODE, CONFIDENTIAL_MARKER),
  sensitive (bool: data_types is not empty), agent_tool, tainted (bool),
  origin ('gateway' | 'log'), forwarded (bool),
  sent_unmasked (bool: the text reached the AI tool as written)
v_tools: one row per AI tool in the inventory.
  tool (slug), name, category, status, risk_score (1 to 5), rating_source, needs_review (bool),
  first_seen, last_seen, requests_14d, teams_14d
v_teams: one row per team, over the last 14 days.
  team, events_14d, sensitive_events_14d, blocked_14d, redacted_14d, warned_14d,
  sent_unmasked_14d, unapproved_tool_events_14d, tools_used_14d
"""

INSTRUCTIONS = f"""You write one PostgreSQL SELECT statement that answers a security \
analyst's question about AI tool usage.

Use only these views:
{SCHEMA}
Rules:
- A single SELECT. No other statement, no other table, no comments.
- "This week" means the last 7 days: ts >= now() - interval '7 days'.
- "Client data" means 'CLIENT' = ANY(data_types). Test other data types the same way.
- Prompts are rows with channel = 'prompt'.
- Give columns short, readable aliases. Order the result so the most important row is first.
- Suggest a chart only when it helps: bar for comparisons, line for a series over days.

Examples:
{{examples}}"""

SUMMARY_INSTRUCTIONS = (
    "You are given an analyst's question, the columns of a result table and its first rows. "
    "Answer the question in one short, plain sentence using only those numbers."
)


class SqlDraft(BaseModel):
    sql: str = Field(description="One PostgreSQL SELECT statement")
    chart: ChartSpec | None = Field(description="A chart of the result, or null")


class NoAnswerError(ValueError):
    """The question could not be turned into a safe query."""


def _examples() -> str:
    return "\n\n".join(
        f"Question: {example.question}\nSQL: {textwrap.dedent(example.sql).strip()}"
        for example in EXAMPLES
    )


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


async def run_readonly(readonly_db: Database, sql: str) -> tuple[list[str], list[list[Any]]]:
    """Run guarded SQL in a read-only transaction with a timeout. `readonly_db` logs in as
    the analyst role, so nothing the query does can reach beyond the three views."""
    async with readonly_db.session() as session:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        await session.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))
        result = await session.execute(text(sql))
        columns = list(result.keys())
        rows = [[_plain(value) for value in row] for row in result.all()]
    return columns, rows


async def answer(readonly_db: Database, llm: LLM, question: str) -> AskResult:
    draft = (
        await llm.structured(
            instructions=INSTRUCTIONS.format(examples=_examples()),
            text=question,
            schema=SqlDraft,
            effort="medium",
        )
    ).value
    try:
        sql = guard(draft.sql)
        columns, rows = await run_readonly(readonly_db, sql)
    except UnsafeSqlError as exc:
        raise NoAnswerError(f"The generated query was rejected: {exc}") from exc
    except DBAPIError as exc:
        raise NoAnswerError("The generated query failed to run. Try rephrasing.") from exc
    chart = draft.chart
    if chart and not {chart.x, *chart.y} <= set(columns):
        chart = None
    table = "\n".join(str(row) for row in rows[:SUMMARY_ROWS])
    summary = await llm.complete(
        instructions=SUMMARY_INSTRUCTIONS,
        text=f"Question: {question}\nColumns: {columns}\nRows:\n{table}",
        effort="low",
    )
    return AskResult(
        answer=summary.value.strip(),
        sql=sql,
        columns=columns,
        rows=rows,
        chart=chart,
        truncated=len(rows) >= MAX_ROWS,
    )
