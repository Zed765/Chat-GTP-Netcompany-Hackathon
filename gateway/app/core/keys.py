"""Key material: taken from the environment, or generated once into the keys volume."""

import base64
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

KEY_BYTES = 32


@dataclass(frozen=True)
class Keys:
    vault: bytes
    pseudonym: bytes
    session: bytes
    readonly_db: bytes


def _load(name: str, keys_dir: Path) -> bytes:
    from_env = os.environ.get(f"ASPIDA_{name.upper()}_KEY")
    if from_env:
        key = base64.urlsafe_b64decode(from_env)
        if len(key) != KEY_BYTES:
            raise ValueError(f"ASPIDA_{name.upper()}_KEY must decode to {KEY_BYTES} bytes")
        return key
    path = keys_dir / f"{name}.key"
    if not path.exists():
        keys_dir.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(secrets.token_bytes(KEY_BYTES))
    return path.read_bytes()


def load_keys(keys_dir: Path) -> Keys:
    return Keys(
        vault=_load("vault", keys_dir),
        pseudonym=_load("pseudonym", keys_dir),
        session=_load("session", keys_dir),
        readonly_db=_load("readonly_db", keys_dir),
    )
