"""Shared contracts between the gateway modules.

Every module (detect, vault, policy, discovery, mcp_proxy, proxy) talks to the others
only through the models here and the protocols in `interfaces.py`.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Tier(StrEnum):
    T0 = "T0"
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"


class Action(StrEnum):
    ALLOW = "allow"
    REDACT = "redact"
    WARN = "warn"
    BLOCK = "block"


class Channel(StrEnum):
    PROMPT = "prompt"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"


class ToolStatus(StrEnum):
    APPROVED = "approved"
    TOLERATED = "tolerated"
    UNAPPROVED = "unapproved"
    UNKNOWN = "unknown"


class Trust(StrEnum):
    TRUSTED = "trusted"
    UNTRUSTED = "untrusted"


class RowSource(StrEnum):
    """Which layer a protected-data row belongs to."""

    DEFAULT = "default"
    SYNCED = "synced"
    UPLOADED = "uploaded"
    SEEDED = "seeded"


class Store(StrEnum):
    TERMS = "terms"
    FINGERPRINTS = "fingerprints"
    PATTERNS = "patterns"


class Role(StrEnum):
    EMPLOYEE = "employee"
    ADMIN = "admin"
    SERVICE = "service"


class InjectionProtection(StrEnum):
    OFF = "off"
    STANDARD = "standard"
    DETAILED = "detailed"


class DataType:
    """Built-in data types. Types are plain strings because a company can add its own."""

    PERSON = "PERSON"
    ORG = "ORG"
    LOCATION = "LOCATION"
    ADDRESS = "ADDRESS"
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    AFM = "AFM"
    AMKA = "AMKA"
    IBAN = "IBAN"
    CARD = "CARD"
    ID_CARD = "ID_CARD"
    SECRET = "SECRET"  # noqa: S105
    CLIENT = "CLIENT"
    CONFIDENTIAL_MARKER = "CONFIDENTIAL_MARKER"
    # Document-level categories (T2 and T3).
    CONTRACT = "CONTRACT"
    FINANCIAL = "FINANCIAL"
    HEALTH = "HEALTH"
    HR = "HR"
    SOURCE_CODE = "SOURCE_CODE"
    CLIENT_CONFIDENTIAL = "CLIENT_CONFIDENTIAL"
    # In a policy rule, every type that is not one of the above: those a company defined
    # itself with a pattern, a term or a document category.
    CUSTOM = "CUSTOM"

    SPAN_TYPES: frozenset[str] = frozenset(
        {PERSON, ORG, LOCATION, ADDRESS, EMAIL, PHONE, AFM, AMKA, IBAN, CARD, ID_CARD, SECRET,
         CLIENT, CONFIDENTIAL_MARKER}
    )  # fmt: skip
    CATEGORIES: frozenset[str] = frozenset(
        {CONTRACT, FINANCIAL, HEALTH, HR, SOURCE_CODE, CLIENT_CONFIDENTIAL}
    )
    BUILT_IN: frozenset[str] = SPAN_TYPES | CATEGORIES | {CUSTOM}


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class Usage(Frozen):
    """Model usage attributable to one request."""

    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cost_usd=self.cost_usd + other.cost_usd,
        )


class StoreRef(Frozen):
    """The protected-data row behind a finding, so the UI can say which store and row matched."""

    store: Store
    row_id: str
    source: RowSource
    label: str = Field(
        description="Row name safe to show: pattern name, document label, term group"
    )


class Finding(Frozen):
    """A sensitive span found by T0 or T1.

    `start` and `end` index the original text given to the detector, and `text` equals
    `original[start:end]`. For a value found inside an encoded run the span covers the whole run.
    """

    data_type: str
    start: int
    end: int
    text: str
    tier: Tier
    score: float = Field(ge=0.0, le=1.0)
    recogniser: str = Field(description="For example `afm`, `pattern:github-token`, `ner:el`")
    match: StoreRef | None = None
    canonical: str | None = Field(
        default=None, description="Canonical entity name, used to link mentions of one entity"
    )
    encoded: bool = False
    maskable: bool = Field(
        default=True, description="False for confidentiality markers: flagged but not masked"
    )


class CategoryFinding(Frozen):
    """A document-level category found by T2 or T3 on masked text."""

    category: str
    tier: Tier
    score: float = Field(ge=0.0, le=1.0)
    conclusive: bool
    match: StoreRef | None = None
    evidence: str = Field(
        description='For example `matches "MSA Helios"` or `resembles a contract`'
    )


class LocalDetection(Frozen):
    findings: tuple[Finding, ...] = Field(description="Sorted by start, never overlapping")
    timings_ms: dict[Tier, float]
    notes: tuple[str, ...] = ()


class ContextualDetection(Frozen):
    categories: tuple[CategoryFinding, ...]
    timings_ms: dict[Tier, float]
    tiers_run: tuple[Tier, ...]
    usage: Usage = Usage()
    error: str | None = None


class MaskedSpan(Frozen):
    """One replaced span, in coordinates of the original text."""

    start: int
    end: int
    placeholder: str
    data_type: str
    tier: Tier
    recogniser: str
    match: StoreRef | None = None
    encoded: bool = False


class MaskResult(Frozen):
    text: str
    spans: tuple[MaskedSpan, ...]
    unmasked: tuple[Finding, ...] = Field(
        default=(), description="Findings that are flagged but left in place"
    )


class RehydrationReport(Frozen):
    sent: int = Field(description="Distinct placeholders forwarded upstream")
    returned: int = Field(description="Distinct placeholders seen in the response and restored")
    unresolved: tuple[str, ...] = Field(
        default=(), description="Placeholder-like tokens that match nothing in the vault"
    )


class PlaceholderInfo(Frozen):
    placeholder: str
    data_type: str


class ToolRef(Frozen):
    slug: str
    name: str
    status: ToolStatus
    category: str | None = None
    upstream_url: str | None = Field(
        default=None, description="Where the gateway forwards prompts for this tool"
    )


class FoundItem(Frozen):
    data_type: str
    count: int
    tier: Tier
    encoded: bool = False
    match_label: str | None = None
    store: Store | None = None
    source: RowSource | None = None


class PolicyContext(Frozen):
    channel: Channel
    data_types: frozenset[str]
    tool: str | None = Field(
        default=None, description="AI tool slug on `prompt`; `<server>.<tool>` on tool channels"
    )
    tool_status: ToolStatus | None = None
    team: str | None = None
    tainted: bool = False
    side_effects: bool = False
    destination: Trust | None = None
    source: Trust | None = None
    detector_error: bool = False


class Explanation(Frozen):
    summary: str = Field(description="One plain sentence: what was found and what was done")
    found: tuple[FoundItem, ...]
    rule: str
    action: Action
    advice: str | None = Field(default=None, description="What to do instead")
    alternatives: tuple[ToolRef, ...] = ()


class PolicyDecision(Frozen):
    action: Action
    rule: str
    policy_version: int
    matched_types: tuple[str, ...]
    explanation: Explanation


class InjectionVerdict(Frozen):
    flagged: bool
    confidence: float = Field(ge=0.0, le=1.0)
    technique: str | None = None
    evidence: str | None = Field(default=None, description="Flagged span; never persisted")
    layers_run: tuple[str, ...] = ()


class Principal(Frozen):
    user_id: str
    display_name: str
    team: str
    role: Role
