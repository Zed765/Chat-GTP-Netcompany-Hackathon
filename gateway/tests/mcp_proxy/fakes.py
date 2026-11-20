"""Small stand-ins for the modules other workstreams own. Each satisfies its protocol in
`core.interfaces`, and the policy reads the real `policies/default.yaml`."""

import re
from collections.abc import Callable, Collection, Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import yaml
from redis.asyncio import Redis

from gateway.app.config import Settings
from gateway.app.core.auth import DEMO_USERS, issue_token
from gateway.app.core.deps import Deps
from gateway.app.core.interfaces import Rehydrator
from gateway.app.core.keys import Keys
from gateway.app.core.services import Services
from gateway.app.core.types import (
    Action,
    ContextualDetection,
    DataType,
    Explanation,
    Finding,
    FoundItem,
    InjectionProtection,
    LocalDetection,
    MaskedSpan,
    MaskResult,
    PlaceholderInfo,
    PolicyContext,
    PolicyDecision,
    Principal,
    RehydrationReport,
    Tier,
    ToolRef,
    ToolStatus,
    Usage,
)
from gateway.app.events.writer import EventRecord, EventWriter
from gateway.app.mcp_proxy import InjectionJudgement, InjectionService
from gateway.app.mcp_proxy.trust import AgentTrust, AgentTrustStore
from gateway.app.privacy.store import SettingsStore
from gateway.tests.doubles import FakeLLM
from mcp_servers.crm.clients import FIXTURE

REPO = Path(__file__).resolve().parents[3]
KEYS = Keys(vault=b"v" * 32, pseudonym=b"p" * 32, session=b"s" * 32, readonly_db=b"r" * 32)
EMPLOYEE, ADMIN = DEMO_USERS[0], DEMO_USERS[1]
PLACEHOLDER = re.compile(r"<[A-Z_]+_\d+>")

_NAMES = sorted(
    {client["legal_name"] for client in FIXTURE}
    | {contact["name"] for client in FIXTURE for contact in client["contacts"]}
    | {"Eleni Papadaki", "Κατερίνα Δημητρίου", "Sophia Mitchell"},
    key=len,
    reverse=True,
)
_PATTERNS = (
    (DataType.EMAIL, re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    (DataType.IBAN, re.compile(r"\bGR\d{25}\b")),
    (DataType.AFM, re.compile(r"\b\d{9}\b")),
    (DataType.PHONE, re.compile(r"\+30(?: \d{2,4}){3}")),
    (DataType.PERSON, re.compile("|".join(re.escape(name) for name in _NAMES))),
)


def bearer(principal: Principal = EMPLOYEE) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_token(principal, KEYS.session, hours=1)}"}


class FakeDetector:
    """Finds emails, IBANs, AFMs, phone numbers and the people and clients of the CRM fixture."""

    async def detect_local(self, text: str) -> LocalDetection:
        matches = sorted(
            (
                (m.start(), m.end(), kind)
                for kind, pattern in _PATTERNS
                for m in pattern.finditer(text)
            ),
            key=lambda found: (found[0], -found[1]),
        )
        findings: list[Finding] = []
        for start, end, kind in matches:
            if findings and start < findings[-1].end:
                continue
            findings.append(
                Finding(
                    data_type=kind,
                    start=start,
                    end=end,
                    text=text[start:end],
                    tier=Tier.T1 if kind == DataType.PERSON else Tier.T0,
                    score=1.0,
                    recogniser="fake",
                )
            )
        return LocalDetection(findings=tuple(findings), timings_ms={Tier.T0: 0.2, Tier.T1: 1.5})

    async def detect_contextual(
        self, masked_text: str, *, local: LocalDetection, force_t3: bool = False
    ) -> ContextualDetection:
        return ContextualDetection(categories=(), timings_ms={}, tiers_run=())


class _NoRehydration:
    def feed(self, chunk: str) -> str:
        return chunk

    def flush(self) -> str:
        return ""

    def report(self) -> RehydrationReport:
        return RehydrationReport(sent=0, returned=0)


class FakeVault:
    """One placeholder per distinct value and conversation, kept in memory."""

    def __init__(self) -> None:
        self.values: dict[str, dict[str, str]] = {}
        self.types: dict[str, dict[str, str]] = {}
        self.ended: list[str] = []

    def _placeholder(self, conversation_id: str, finding: Finding) -> str:
        values = self.values.setdefault(conversation_id, {})
        types = self.types.setdefault(conversation_id, {})
        for placeholder, value in values.items():
            if value == finding.text and types[placeholder] == finding.data_type:
                return placeholder
        number = sum(kind == finding.data_type for kind in types.values()) + 1
        placeholder = f"<{finding.data_type}_{number}>"
        values[placeholder], types[placeholder] = finding.text, finding.data_type
        return placeholder

    async def mask(
        self, conversation_id: str, text: str, findings: Sequence[Finding]
    ) -> MaskResult:
        spans = [
            MaskedSpan(
                start=f.start,
                end=f.end,
                placeholder=self._placeholder(conversation_id, f),
                data_type=f.data_type,
                tier=f.tier,
                recogniser=f.recogniser,
            )
            for f in findings
        ]
        for span in reversed(spans):
            text = text[: span.start] + span.placeholder + text[span.end :]
        return MaskResult(text=text, spans=tuple(spans))

    async def rehydrator(self, conversation_id: str, sent: Collection[str]) -> Rehydrator:
        return _NoRehydration()

    async def as_sent(self, conversation_id: str, texts: Sequence[str]) -> list[str]:
        swapped = list(texts)
        for placeholder, value in self.values.get(conversation_id, {}).items():
            swapped = [text.replace(value, placeholder) for text in swapped]
        return swapped

    async def resolve(self, conversation_id: str, text: str) -> tuple[str, RehydrationReport]:
        values = self.values.get(conversation_id, {})
        seen = set(PLACEHOLDER.findall(text))
        restored = PLACEHOLDER.sub(lambda match: values.get(match.group(), match.group()), text)
        report = RehydrationReport(
            sent=len(values),
            returned=len(seen & set(values)),
            unresolved=tuple(sorted(seen - set(values))),
        )
        return restored, report

    async def describe(self, conversation_id: str) -> list[PlaceholderInfo]:
        return [
            PlaceholderInfo(placeholder=placeholder, data_type=kind)
            for placeholder, kind in self.types.get(conversation_id, {}).items()
        ]

    async def end(self, conversation_id: str) -> None:
        self.ended.append(conversation_id)
        self.values.pop(conversation_id, None)
        self.types.pop(conversation_id, None)


def _matches(when: Mapping[str, Any], ctx: PolicyContext) -> bool:
    checks: dict[str, Callable[[Any], bool]] = {
        "channel": lambda value: ctx.channel == value,
        "data": lambda value: bool(ctx.data_types & set(value)),
        "tool_status": lambda value: ctx.tool_status in value,
        "side_effects": lambda value: ctx.side_effects is value,
        "tainted": lambda value: ctx.tainted is value,
        "destination": lambda value: ctx.destination == value,
        "source": lambda value: ctx.source == value,
    }
    return all(checks[key](value) for key, value in when.items())


class YamlPolicy:
    """First matching rule of the default policy file wins, as in the real engine."""

    def __init__(
        self,
        level: InjectionProtection | None = None,
        actions: Mapping[str, Action] | None = None,
    ) -> None:
        document = yaml.safe_load((REPO / "policies" / "default.yaml").read_text("utf-8"))
        self._version: int = document["version"]
        self._rules: list[dict[str, Any]] = document["rules"]
        self.actions = dict(actions or {})
        self.level = level or InjectionProtection(document["injection_protection"])

    @property
    def version(self) -> int:
        return self._version

    @property
    def injection_protection(self) -> InjectionProtection:
        return self.level

    async def decide(self, ctx: PolicyContext, found: Sequence[FoundItem]) -> PolicyDecision:
        rule = next(rule for rule in self._rules if _matches(rule.get("when", {}), ctx))
        name: str = rule["name"]
        action = self.actions.get(name, Action(rule["action"]))
        return PolicyDecision(
            action=action,
            rule=name,
            policy_version=self._version,
            matched_types=tuple(sorted(ctx.data_types)),
            explanation=Explanation(
                summary=f"Rule {name} applies.", found=tuple(found), rule=name, action=action
            ),
        )


class FakeEvents:
    def __init__(self) -> None:
        self.records: list[EventRecord] = []

    async def write(self, record: EventRecord) -> int:
        self.records.append(record)
        return len(self.records)


class FakeInventory:
    """Two approved tools. Like the real inventory, it finds a tool by slug or by domain and
    answers for anything else with an unknown tool named after what was asked for."""

    def __init__(self) -> None:
        self._by_slug = {
            "company-assistant": ToolRef(
                slug="company-assistant", name="Company assistant", status=ToolStatus.APPROVED
            ),
            "athena-assist": ToolRef(
                slug="athena-assist", name="Athena Assist", status=ToolStatus.APPROVED
            ),
        }
        self._by_domain = {"athena.example": self._by_slug["athena-assist"]}

    def tools(self) -> list[ToolRef]:
        return list(self._by_slug.values())

    async def resolve(self, tool: str) -> ToolRef:
        key = tool.strip().lower()
        found = self._by_slug.get(key) or self._by_domain.get(key)
        return found or ToolRef(slug=key, name=tool, status=ToolStatus.UNKNOWN)

    async def approved_alternatives(self, category: str | None) -> list[ToolRef]:
        return []


CONFIRMS = InjectionJudgement(is_injection=True, confidence=0.95, evidence="", technique="")


def judge(judgement: InjectionJudgement | Exception = CONFIRMS) -> FakeLLM:
    """The model behind injection layer 2, answering with `judgement` or failing with it.
    By default it confirms what it is shown: at `standard`, only what layer 1 flagged."""
    usage = Usage(input_tokens=900, output_tokens=40, cost_usd=0.00011)
    return FakeLLM(answers={"InjectionJudgement": judgement}, usage=usage)


def injection_service(llm: FakeLLM | None = None) -> InjectionService:
    deps = SimpleNamespace(llm=llm or judge(), settings=Settings())
    return InjectionService(cast(Deps, deps))


class MemorySettings:
    """Settings kept in a dict, in place of the database table."""

    def __init__(self) -> None:
        self._values: dict[str, Any] = {}

    async def get(self, key: str, default: Any) -> Any:
        return self._values.get(key, default)

    async def put(self, key: str, value: Any) -> None:
        self._values[key] = value


class QuietBus:
    """One process, so there is no other worker to tell."""

    async def publish(self, topic: str) -> None:
        return None


class Stack(SimpleNamespace):
    """The fakes behind a `Services`, kept reachable so tests can look inside them."""

    vault: FakeVault
    events: FakeEvents
    policy: YamlPolicy
    llm: FakeLLM
    services: Services


def make_stack(
    redis: Redis,
    *,
    policy: YamlPolicy | None = None,
    llm: FakeLLM | None = None,
    events: EventWriter | None = None,
) -> Stack:
    """`events` swaps the recording fake for the real writer."""
    stack = Stack(
        vault=FakeVault(),
        events=events or FakeEvents(),
        policy=policy or YamlPolicy(),
        llm=llm or judge(),
    )
    stack.services = cast(
        Services,
        SimpleNamespace(
            settings=Settings(),
            keys=KEYS,
            redis=redis,
            llm=stack.llm,
            events=stack.events,
            detector=FakeDetector(),
            vault=stack.vault,
            inventory=FakeInventory(),
            policy=stack.policy,
            injection=injection_service(stack.llm),
            bus=QuietBus(),
            agent_trust=AgentTrustStore(
                cast(SettingsStore, MemorySettings()), AgentTrust.configured(Settings())
            ),
        ),
    )
    return stack
