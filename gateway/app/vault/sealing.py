"""Cryptography for the vault: AES-GCM for the values, keyed hashes for everything that
has to be looked up, so Redis never holds a readable value, name or conversation ID."""

import base64
import hashlib
import hmac
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_BYTES = 12
TOKEN_HEX_CHARS = 32
_INDEX_KEY_LABEL = b"aspida/vault/index"


def _frame(*parts: str) -> bytes:
    """Length-prefixed, so no two lists of parts share an encoding."""
    encoded = [part.encode() for part in parts]
    return b"".join(len(part).to_bytes(4, "big") + part for part in encoded)


class Sealer:
    def __init__(self, key: bytes) -> None:
        self._aead = AESGCM(key)
        self._index_key = hmac.digest(key, _INDEX_KEY_LABEL, hashlib.sha256)

    def seal(self, conversation_id: str, placeholder: str, value: str) -> str:
        """Encrypt one value under a fresh nonce. The conversation and the placeholder are
        bound in as associated data, so a value copied anywhere else does not open."""
        nonce = secrets.token_bytes(NONCE_BYTES)
        sealed = self._aead.encrypt(nonce, value.encode(), _frame(conversation_id, placeholder))
        return base64.b64encode(nonce + sealed).decode("ascii")

    def open(self, conversation_id: str, placeholder: str, sealed: str) -> str | None:
        """The value, or None if it was sealed with another key, conversation or placeholder."""
        try:
            raw = base64.b64decode(sealed, validate=True)
            opened = self._aead.decrypt(
                raw[:NONCE_BYTES], raw[NONCE_BYTES:], _frame(conversation_id, placeholder)
            )
        except (InvalidTag, ValueError):
            return None
        return opened.decode()

    def token(self, *parts: str) -> str:
        """A keyed hash that stands in for a lookup key in Redis."""
        digest = hmac.digest(self._index_key, _frame(*parts), hashlib.sha256)
        return digest.hex()[:TOKEN_HEX_CHARS]
