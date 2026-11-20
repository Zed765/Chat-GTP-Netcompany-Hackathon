"""The vault: reversible pseudonymisation for one conversation at a time."""

import asyncio
import re
from collections.abc import Collection, Sequence
from weakref import WeakValueDictionary

from redis.asyncio import Redis

from gateway.app.core.types import (
    DataType,
    Finding,
    MaskedSpan,
    MaskResult,
    PlaceholderInfo,
    RehydrationReport,
)
from gateway.app.vault.linking import Linker, link_all, mention_of
from gateway.app.vault.placeholders import (
    SECRET_PLACEHOLDER,
    PlaceholderSpan,
    find_placeholders,
    parse,
)
from gateway.app.vault.rehydration import StreamRehydrator
from gateway.app.vault.sealing import Sealer
from gateway.app.vault.store import DEFAULT_PREFIX, VaultStore


class VaultService:
    """Implements `core.interfaces.Vault`.

    A placeholder restores to the first surface form its entity had in the conversation.
    """

    def __init__(
        self, redis: Redis, key: bytes, ttl_seconds: int, *, key_prefix: str = DEFAULT_PREFIX
    ) -> None:
        self._store = VaultStore(redis, Sealer(key), ttl_seconds, key_prefix)
        # Two texts of one conversation masked at once would both number a new entity
        # from the same count. One gateway process serves all requests, so a lock is enough.
        self._locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()

    async def mask(
        self, conversation_id: str, text: str, findings: Sequence[Finding]
    ) -> MaskResult:
        """Replace each maskable finding with its conversation's placeholder.

        Secrets become `<SECRET_REDACTED>` and are never stored. A finding that touches a
        placeholder this conversation already holds is ignored: the text was masked before.
        Text that merely looks like a placeholder protects nothing.
        """
        already_masked = await self._held_placeholders(conversation_id, text) if findings else []
        targets: list[Finding] = []
        unmasked: list[Finding] = []
        end_of_previous = 0
        for finding in findings:
            if not end_of_previous <= finding.start < finding.end <= len(text):
                raise ValueError("findings must be sorted, inside the text and not overlap")
            end_of_previous = finding.end
            if not finding.maskable:
                unmasked.append(finding)
            elif not _touches(finding, already_masked):
                targets.append(finding)

        stored = [finding for finding in targets if finding.data_type != DataType.SECRET]
        placeholders = iter(await self._link(conversation_id, text, stored))
        spans = [
            MaskedSpan(
                start=finding.start,
                end=finding.end,
                placeholder=(
                    SECRET_PLACEHOLDER
                    if finding.data_type == DataType.SECRET
                    else next(placeholders)
                ),
                data_type=finding.data_type,
                tier=finding.tier,
                recogniser=finding.recogniser,
                match=finding.match,
                encoded=finding.encoded,
            )
            for finding in targets
        ]
        return MaskResult(text=_replace(text, spans), spans=tuple(spans), unmasked=tuple(unmasked))

    async def _link(
        self, conversation_id: str, text: str, findings: Sequence[Finding]
    ) -> list[str]:
        if not findings:
            return []
        mentions = [mention_of(finding, text[finding.start : finding.end]) for finding in findings]
        entries = {entry for mention in mentions for entry in mention.link_keys()}
        lock = self._locks.setdefault(conversation_id, asyncio.Lock())
        async with lock:
            linker = Linker(await self._store.read_links(conversation_id, entries))
            placeholders = link_all(linker, mentions)
            if linker.changed:
                await self._store.write(conversation_id, linker.changed, linker.created)
        return placeholders

    async def rehydrator(self, conversation_id: str, sent: Collection[str]) -> StreamRehydrator:
        """A streaming restorer for one response. It restores any placeholder the
        conversation's vault holds; `sent` only feeds the integrity report."""
        return StreamRehydrator(await self._store.read_values(conversation_id), sent)

    async def resolve(self, conversation_id: str, text: str) -> tuple[str, RehydrationReport]:
        rehydrator = await self.rehydrator(conversation_id, ())
        return rehydrator.feed(text) + rehydrator.flush(), rehydrator.report()

    async def _held_placeholders(self, conversation_id: str, text: str) -> list[PlaceholderSpan]:
        found = find_placeholders(text)
        if not found:
            return []
        held = await self._store.placeholders(conversation_id)
        return [
            span
            for span in found
            if span.placeholder in held or span.placeholder == SECRET_PLACEHOLDER
        ]

    async def as_sent(self, conversation_id: str, texts: Sequence[str]) -> list[str]:
        """Each text with the values this conversation holds replaced by their placeholders:
        how it read on the model's side. Values are only looked up, so nothing comes back
        that the caller did not send, and nothing is stored."""
        values = await self._store.read_values(conversation_id)
        placeholders = {value: token for token, value in sorted(values.items()) if value.strip()}
        if not placeholders:
            return list(texts)
        # Longest first, so "Maria Papadopoulou" wins over a "Maria" held on its own; and whole
        # values only, so a held "5" does not turn up inside "2025".
        longest_first = sorted(placeholders, key=len, reverse=True)
        held = re.compile(rf"(?<!\w)(?:{'|'.join(map(re.escape, longest_first))})(?!\w)")
        return [held.sub(lambda match: placeholders[match.group()], text) for text in texts]

    async def describe(self, conversation_id: str) -> list[PlaceholderInfo]:
        """Placeholders and their types, in type and number order. No value is read."""
        held = await self._store.placeholders(conversation_id)
        typed = sorted((parsed, token) for token in held if (parsed := parse(token)))
        return [PlaceholderInfo(placeholder=token, data_type=label) for (label, _), token in typed]

    async def end(self, conversation_id: str) -> None:
        await self._store.delete(conversation_id)


def _touches(finding: Finding, placeholders: Sequence[PlaceholderSpan]) -> bool:
    return any(span.start < finding.end and finding.start < span.end for span in placeholders)


def _replace(text: str, spans: Sequence[MaskedSpan]) -> str:
    parts: list[str] = []
    position = 0
    for span in spans:
        parts += text[position : span.start], span.placeholder
        position = span.end
    parts.append(text[position:])
    return "".join(parts)
