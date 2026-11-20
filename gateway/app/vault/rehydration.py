"""Restoring placeholders in a response, including one that arrives in chunks."""

from collections.abc import Collection, Mapping

from gateway.app.core.types import RehydrationReport
from gateway.app.vault.placeholders import (
    SECRET_PLACEHOLDER,
    candidates,
    held_back_from,
    lookup_key,
)


class StreamRehydrator:
    """Restores every placeholder the conversation's vault knows, in text fed in chunks of
    any size. The output is the same however the text is cut.

    A chunk can end in the middle of a placeholder, so `feed` keeps back a tail that could
    still become one and releases it once it resolves or cannot match. Unknown tokens are
    left as they are and reported.
    """

    def __init__(self, values: Mapping[str, str], sent: Collection[str]) -> None:
        self._values = dict(values)
        self._by_key = {lookup_key(placeholder): placeholder for placeholder in values}
        self._key_prefixes = {
            key[:length] for key in self._by_key for length in range(1, len(key) + 1)
        }
        self._sent = {placeholder for placeholder in sent if placeholder != SECRET_PLACEHOLDER}
        self._before = ""
        self._held = ""
        self._returned: set[str] = set()
        self._unresolved: dict[str, None] = {}

    def feed(self, chunk: str) -> str:
        self._held += chunk
        seen = self._before + self._held
        cut = held_back_from(seen, self._key_prefixes.__contains__) - len(self._before)
        return self._release(max(cut, 0))

    def flush(self) -> str:
        return self._release(len(self._held))

    def report(self) -> RehydrationReport:
        return RehydrationReport(
            sent=len(self._sent),
            returned=len(self._returned),
            unresolved=tuple(self._unresolved),
        )

    def _release(self, cut: int) -> str:
        ready, self._held = self._held[:cut], self._held[cut:]
        # The last character already released stays in view: a token is not a placeholder
        # when it continues a word that came before it.
        text, skip = self._before + ready, len(self._before)
        self._before = text[-1:]
        restored: list[str] = []
        position = skip
        for candidate in candidates(text):
            if candidate.start < skip:
                continue
            placeholder = self._by_key.get(candidate.key)
            if placeholder is None:
                if candidate.well_formed:
                    self._unresolved.setdefault(candidate.well_formed)
                continue
            restored += text[position : candidate.start], self._values[placeholder]
            position = candidate.end
            self._returned.add(placeholder)
        restored.append(text[position:])
        return "".join(restored)
