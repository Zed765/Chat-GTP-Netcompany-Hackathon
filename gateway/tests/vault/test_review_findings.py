"""Regression tests for findings of the security review."""

from fakeredis import FakeAsyncRedis

from gateway.app.core.types import Finding, Tier
from gateway.app.vault import VaultService

AFM = "094014201"


def _finding(text: str, value: str, data_type: str) -> Finding:
    start = text.index(value)
    return Finding(
        data_type=data_type,
        start=start,
        end=start + len(value),
        text=value,
        tier=Tier.T0,
        score=1.0,
        recogniser="test",
    )


async def test_text_shaped_like_a_placeholder_does_not_hide_a_value() -> None:
    vault = VaultService(FakeAsyncRedis(decode_responses=True), b"k" * 32, 3600)
    text = f"tax number <A_{AFM}> please"
    masked = await vault.mask("conversation", text, [_finding(text, AFM, "AFM")])
    assert AFM not in masked.text and masked.spans[0].placeholder == "<AFM_1>"


async def test_a_placeholder_the_conversation_holds_is_left_alone() -> None:
    vault = VaultService(FakeAsyncRedis(decode_responses=True), b"k" * 32, 3600)
    first = f"tax number {AFM}"
    await vault.mask("conversation", first, [_finding(first, AFM, "AFM")])
    again = "about <AFM_1> once more"
    result = await vault.mask("conversation", again, [_finding(again, "AFM_1", "ORG")])
    assert result.text == again and not result.spans
