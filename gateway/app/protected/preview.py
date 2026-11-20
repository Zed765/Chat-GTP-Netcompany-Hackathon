"""Masks a test prompt the way the vault would, without a vault: nothing is stored."""

from collections.abc import Sequence

from gateway.app.core.textnorm import entity_key
from gateway.app.core.types import DataType, Finding

SECRET_PLACEHOLDER = "<SECRET_REDACTED>"  # noqa: S105


def mask_preview(text: str, findings: Sequence[Finding]) -> tuple[str, list[str | None]]:
    """The masked text, and for each finding its placeholder (None when it is not masked).
    Mentions of one entity share a placeholder, numbered per type in order of appearance."""
    numbers: dict[tuple[str, str], int] = {}
    counts: dict[str, int] = {}
    placeholders: list[str | None] = []
    parts: list[str] = []
    cursor = 0
    for finding in findings:
        if not finding.maskable:
            placeholders.append(None)
            continue
        if finding.data_type == DataType.SECRET:
            placeholder = SECRET_PLACEHOLDER
        else:
            entity = (
                finding.data_type,
                entity_key(finding.canonical or finding.text) or finding.text,
            )
            if entity not in numbers:
                counts[finding.data_type] = counts.get(finding.data_type, 0) + 1
                numbers[entity] = counts[finding.data_type]
            placeholder = f"<{finding.data_type}_{numbers[entity]}>"
        placeholders.append(placeholder)
        parts += (text[cursor : finding.start], placeholder)
        cursor = finding.end
    parts.append(text[cursor:])
    return "".join(parts), placeholders
