"""Loads the default pack into the stores. Safe to run on every start: rows are replaced
only when the pack's content changed, and rows an analyst switched off stay off."""

from cryptography.exceptions import InvalidTag
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.core.types import RowSource, Store
from gateway.app.protected.crypto import TermCipher
from gateway.app.protected.models import CustomPattern, DefaultSwitch, ProtectedTerm
from gateway.app.protected.pack import PatternPack, TermPack

DEFAULT = RowSource.DEFAULT.value


class Switches:
    """The default rows and groups an analyst switched off."""

    def __init__(self, rows: set[tuple[str, str]], groups: set[tuple[str, str]]) -> None:
        self._rows = rows
        self._groups = groups

    @classmethod
    async def load(cls, session: AsyncSession) -> "Switches":
        switches = (await session.execute(select(DefaultSwitch))).scalars().all()
        return cls(
            {(switch.store, switch.key) for switch in switches if not switch.is_group},
            {(switch.store, switch.key) for switch in switches if switch.is_group},
        )

    def row_is_off(self, store: Store, key: str) -> bool:
        return (store.value, key) in self._rows

    def is_on(self, store: Store, group: str, key: str) -> bool:
        return (store.value, group) not in self._groups and not self.row_is_off(store, key)


async def set_switch(
    session: AsyncSession, store: Store, key: str, *, is_group: bool, off: bool
) -> None:
    await session.execute(
        delete(DefaultSwitch).where(
            DefaultSwitch.store == store.value,
            DefaultSwitch.key == key,
            DefaultSwitch.is_group == is_group,
        )
    )
    if off:
        session.add(DefaultSwitch(store=store.value, key=key, is_group=is_group))


async def _is_current(
    session: AsyncSession, model: type[ProtectedTerm] | type[CustomPattern], version: str
) -> bool:
    versions = (
        await session.execute(select(model.pack_version).where(model.source == DEFAULT).distinct())
    ).scalars()
    return set(versions) == {version}


async def _readable(session: AsyncSession, cipher: TermCipher) -> bool:
    sample = (
        await session.execute(
            select(ProtectedTerm.term).where(ProtectedTerm.source == DEFAULT).limit(1)
        )
    ).scalar_one_or_none()
    if sample is None:
        return False
    try:
        cipher.decrypt(sample)
    except InvalidTag:
        return False
    return True


async def sync_terms(
    session: AsyncSession, cipher: TermCipher, pack: TermPack, version: str
) -> bool:
    """Replace the default terms when the pack changed, or when the vault key did and the
    stored rows can no longer be read. Returns whether it did."""
    if await _is_current(session, ProtectedTerm, version) and await _readable(session, cipher):
        return False
    switches = await Switches.load(session)
    await session.execute(delete(ProtectedTerm).where(ProtectedTerm.source == DEFAULT))
    rows = []
    seen: set[str] = set()
    for group in pack.groups:
        for term in group.terms:
            key = cipher.lookup_key(group.name, term)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "source": DEFAULT,
                    "group_name": group.name,
                    "data_type": group.data_type,
                    "term": cipher.encrypt(term),
                    "aliases": None,
                    "term_hmac": key,
                    "enabled": switches.is_on(Store.TERMS, group.name, key),
                    "pack_version": version,
                }
            )
    await session.execute(insert(ProtectedTerm), rows)
    return True


async def sync_patterns(session: AsyncSession, pack: PatternPack, version: str) -> bool:
    if await _is_current(session, CustomPattern, version):
        return False
    switches = await Switches.load(session)
    await session.execute(delete(CustomPattern).where(CustomPattern.source == DEFAULT))
    rows = [
        {
            "source": DEFAULT,
            "group_name": group.name,
            "name": entry.name,
            "regex": entry.regex,
            "data_type": entry.data_type or group.data_type,
            "enabled": switches.is_on(Store.PATTERNS, group.name, entry.name),
            "pack_version": version,
        }
        for group in pack.groups
        for entry in group.patterns
    ]
    await session.execute(insert(CustomPattern), rows)
    return True
