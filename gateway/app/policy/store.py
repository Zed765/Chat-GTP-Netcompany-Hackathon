"""Saved policies. Every change is a new row in `policy_versions`; exactly one row is active."""

from collections.abc import Sequence

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.policy.models import PolicyVersion

_VERSIONS_LOCK = 741_002


async def active(session: AsyncSession) -> PolicyVersion | None:
    return (
        await session.execute(select(PolicyVersion).where(PolicyVersion.active))
    ).scalar_one_or_none()


async def by_version(session: AsyncSession, version: int) -> PolicyVersion | None:
    return await session.get(PolicyVersion, version)


async def newest_first(session: AsyncSession) -> Sequence[PolicyVersion]:
    statement = select(PolicyVersion).order_by(PolicyVersion.version.desc())
    return (await session.execute(statement)).scalars().all()


async def save_as_active(
    session: AsyncSession, yaml_text: str, *, author: str, note: str | None
) -> PolicyVersion:
    await _lock(session)
    latest = (await session.execute(select(func.max(PolicyVersion.version)))).scalar_one()
    await session.execute(update(PolicyVersion).where(PolicyVersion.active).values(active=False))
    row = PolicyVersion(
        version=(latest or 0) + 1, yaml=yaml_text, note=note, author=author, active=True
    )
    session.add(row)
    await session.flush()
    return row


async def active_or_first(session: AsyncSession, first_yaml: str) -> PolicyVersion:
    """The active policy; on an empty table, `first_yaml` saved as version 1."""
    await _lock(session)
    return await active(session) or await save_as_active(
        session, first_yaml, author="system", note="Default policy"
    )


async def _lock(session: AsyncSession) -> None:
    # Serialises writers, so version numbers never collide and one row stays active.
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _VERSIONS_LOCK})
