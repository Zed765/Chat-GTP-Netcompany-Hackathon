import pytest

from gateway.app.core.types import ToolStatus
from gateway.app.discovery.index import ToolIndex, host_of, with_parents
from gateway.app.discovery.models import Tool


def _tool(
    slug: str,
    domains: list[str],
    status: str = "unapproved",
    category: str = "chat assistant",
    risk: int = 3,
    upstream: str | None = None,
) -> Tool:
    return Tool(
        slug=slug,
        name=slug.replace("-", " ").title(),
        domains=domains,
        category=category,
        status=status,
        risk_score=risk,
        upstream_url=upstream,
    )


INDEX = ToolIndex.of(
    [
        _tool("chatgpt", ["chatgpt.com", "chat.openai.com"]),
        _tool("openai-api", ["api.openai.com"], status="tolerated", category="model API"),
        _tool("athena-assist", ["athena-assist.example"], "approved", upstream="http://mock/a"),
        _tool("big-suite", ["suite.example"], "approved", risk=1),
        _tool("safe-chat", ["safechat.example"], "approved", risk=2),
        _tool("code-helper", ["codehelper.example"], "approved", category="coding assistant"),
        _tool("company-assistant", [], "approved", category="in-house assistant", risk=1),
    ]
)


@pytest.mark.parametrize(
    ("value", "host"),
    [
        ("chatgpt.com:443", "chatgpt.com"),
        ("https://Chat.OpenAI.com/c/123?model=x", "chat.openai.com"),
        ("http://user:pw@api.openai.com:8443/v1", "api.openai.com"),
        ("claude.ai.", "claude.ai"),
        ("  gemini.google.com  ", "gemini.google.com"),
        ("[2001:db8::1]:443", "2001:db8::1"),
        ("http://[broken", ""),
        ("", ""),
    ],
)
def test_host_of(value: str, host: str) -> None:
    assert host_of(value) == host


def test_parents_stop_before_the_top_level_domain() -> None:
    assert list(with_parents("a.b.example.com")) == [
        "a.b.example.com",
        "b.example.com",
        "example.com",
    ]
    assert list(with_parents("example.com")) == ["example.com"]


@pytest.mark.parametrize(
    ("tool", "slug"),
    [
        ("chatgpt", "chatgpt"),
        ("ChatGPT", "chatgpt"),
        ("chatgpt.com", "chatgpt"),
        ("https://chatgpt.com/c/42", "chatgpt"),
        ("files.chatgpt.com", "chatgpt"),
        ("eu.files.chat.openai.com:443", "chatgpt"),
        # The most specific domain wins.
        ("api.openai.com", "openai-api"),
        ("eu.api.openai.com", "openai-api"),
    ],
)
def test_find_by_slug_domain_and_subdomain(tool: str, slug: str) -> None:
    found = INDEX.find(tool)
    assert found is not None and found.slug == slug


@pytest.mark.parametrize("tool", ["openai.com", "notchatgpt.com", "com", "unheard-of", ""])
def test_unlisted_names_are_not_found(tool: str) -> None:
    assert INDEX.find(tool) is None


def test_reference_carries_what_the_proxy_needs() -> None:
    athena = INDEX.find("athena-assist.example")
    assert athena is not None
    assert (athena.status, athena.category, athena.upstream_url) == (
        ToolStatus.APPROVED,
        "chat assistant",
        "http://mock/a",
    )


def test_alternatives_are_approved_same_category_first_then_general_purpose() -> None:
    for_chat = [tool.slug for tool in INDEX.approved_alternatives("chat assistant")]
    # The tool the gateway can forward to comes first, then the lower risk.
    assert for_chat == ["athena-assist", "big-suite", "safe-chat"]
    for_code = [tool.slug for tool in INDEX.approved_alternatives("coding assistant")]
    assert for_code == ["code-helper", "athena-assist", "big-suite"]
    unknown_category = [tool.slug for tool in INDEX.approved_alternatives(None)]
    assert unknown_category == for_chat
    assert "company-assistant" not in for_chat + for_code
