"""Hand-built findings, standing in for the detector."""

import re
from collections.abc import Mapping

from gateway.app.core.types import Finding, Tier

CONVERSATION = "0123456789abcdef:client: chosen/id {1} *"
VAULT_KEY = b"v" * 32
TTL_SECONDS = 24 * 3600


def finding(data_type: str, start: int, surface: str, **fields: object) -> Finding:
    return Finding.model_validate(
        {
            "data_type": data_type,
            "start": start,
            "end": start + len(surface),
            "text": surface,
            "tier": Tier.T1,
            "score": 0.9,
            "recogniser": "test",
            **fields,
        }
    )


def found(text: str, entities: Mapping[str, str], **fields: object) -> list[Finding]:
    """A finding for every occurrence of each surface form, longest form first where two
    start at the same place, sorted and never overlapping."""
    longest_first = sorted(entities, key=len, reverse=True)
    pattern = re.compile("|".join(re.escape(surface) for surface in longest_first))
    return [
        finding(entities[match.group()], match.start(), match.group(), **fields)
        for match in pattern.finditer(text)
    ]
