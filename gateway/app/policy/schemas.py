from datetime import datetime

from pydantic import BaseModel, Field

from gateway.app.core.types import Action, InjectionProtection


class PolicyVersionSummary(BaseModel):
    version: int
    note: str | None
    author: str
    created: datetime
    active: bool


class PolicyOut(PolicyVersionSummary):
    yaml: str
    injection_protection: InjectionProtection


class PolicyText(BaseModel):
    yaml: str


class ValidationIssue(BaseModel):
    path: str = Field(description="Where in the document, for example `rules[2].when.data`")
    message: str
    line: int | None = None


class ValidateResult(BaseModel):
    valid: bool
    issues: list[ValidationIssue]


class DraftRequest(BaseModel):
    instruction: str = Field(min_length=3, max_length=500)
    yaml: str


class DraftResult(BaseModel):
    yaml: str
    rule_name: str | None
    explanation: str


class ReplayRequest(BaseModel):
    yaml: str
    days: int = Field(default=7, ge=1, le=90)


class ReplayTransition(BaseModel):
    from_action: Action
    to_action: Action
    count: int


class ReplayBreakdown(BaseModel):
    key: str
    total: int
    changed: int


class ReplayResult(BaseModel):
    days: int
    events: int
    changed: int
    transitions: list[ReplayTransition]
    by_team: list[ReplayBreakdown]
    by_tool: list[ReplayBreakdown]


class ActivateRequest(BaseModel):
    yaml: str
    note: str | None = Field(default=None, max_length=300)


class InjectionProtectionBody(BaseModel):
    level: InjectionProtection
