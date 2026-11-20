from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from gateway.app.core.types import Action, Channel, ToolStatus


class ActionCount(BaseModel):
    action: Action
    count: int


class TypeCount(BaseModel):
    data_type: str
    count: int


class ToolCount(BaseModel):
    tool: str
    name: str
    status: ToolStatus
    count: int


class Heatmap(BaseModel):
    """`cells[i][j]` is the number of events from `teams[i]` carrying `data_types[j]`."""

    teams: list[str]
    data_types: list[str]
    cells: list[list[int]]


class TrendPoint(BaseModel):
    day: date
    total: int
    sensitive: int
    allow: int
    redact: int
    warn: int
    block: int


class Overview(BaseModel):
    days: int
    generated: datetime
    prompts_inspected: int
    sensitive_share: float = Field(ge=0.0, le=1.0)
    actions: list[ActionCount]
    top_data_types: list[TypeCount]
    top_unapproved_tools: list[ToolCount]
    heatmap: Heatmap
    trend: list[TrendPoint]


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)


class ChartSpec(BaseModel):
    kind: Literal["bar", "line"]
    x: str
    y: list[str]


class AskResult(BaseModel):
    answer: str = Field(description="One short sentence")
    sql: str
    columns: list[str]
    rows: list[list[Any]]
    chart: ChartSpec | None
    truncated: bool


class Suggestion(BaseModel):
    question: str


class EventOut(BaseModel):
    """An event as analysts see it: team level, no user identity."""

    id: int
    ts: datetime
    team: str
    tool: str | None
    tool_status: ToolStatus | None
    channel: Channel
    action: Action
    rule: str
    policy_version: int
    data_counts: dict[str, int]
    masked_snippet: str | None
    forwarded: bool
    sent_unmasked: bool = Field(description="The text reached the AI tool as written")
    origin: str
    agent_tool: str | None
    tainted: bool
    injection_flagged: bool


class EventPage(BaseModel):
    total: int
    items: list[EventOut]
