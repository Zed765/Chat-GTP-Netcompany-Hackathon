"""Protected terms are sensitive in themselves (they are the client list), so they are
stored as AES-GCM ciphertext under keys derived from the vault key."""

import hashlib
import hmac
import json
import secrets

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from gateway.app.core.textnorm import fold

NONCE_BYTES = 12
KEY_BYTES = 32


def _derive(vault_key: bytes, purpose: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=KEY_BYTES, salt=None, info=purpose).derive(
        vault_key
    )


class TermCipher:
    def __init__(self, vault_key: bytes) -> None:
        self._aead = AESGCM(_derive(vault_key, b"aspida/protected-terms/encryption"))
        self._mac_key = _derive(vault_key, b"aspida/protected-terms/lookup")

    def encrypt(self, plaintext: str) -> bytes:
        nonce = secrets.token_bytes(NONCE_BYTES)
        return nonce + self._aead.encrypt(nonce, plaintext.encode(), None)

    def decrypt(self, blob: bytes) -> str:
        return self._aead.decrypt(blob[:NONCE_BYTES], blob[NONCE_BYTES:], None).decode()

    def encrypt_list(self, items: list[str]) -> bytes:
        return self.encrypt(json.dumps(items, ensure_ascii=False))

    def decrypt_list(self, blob: bytes | None) -> tuple[str, ...]:
        return tuple(json.loads(self.decrypt(blob))) if blob else ()

    def lookup_key(self, group: str, term: str) -> str:
        """Keyed hash that finds a duplicate term without decrypting, and reveals nothing."""
        message = f"{group}\x00{fold(' '.join(term.split()))}".encode()
        return hmac.new(self._mac_key, message, hashlib.sha256).hexdigest()

    def content_hash(self, text: str) -> str:
        """Keyed hash of a document's text, so a duplicate upload is recognised."""
        message = " ".join(text.split()).encode()
        return hmac.new(self._mac_key, b"document\x00" + message, hashlib.sha256).hexdigest()
