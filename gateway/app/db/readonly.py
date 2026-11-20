"""The analyst chat's own database login: a role that can read three views and nothing else."""

import re

from sqlalchemy import text
from sqlalchemy.engine import make_url

from gateway.app.db.session import Database

READONLY_ROLE = "aspida_readonly"
_SAFE_PASSWORD = re.compile(r"[A-Za-z0-9_\-]{16,}")


async def readonly_database(db: Database, url: str, password: str) -> Database:
    """Give the read-only role a password and open a connection pool that logs in as it.

    The role is created without a login by the migration. Its defaults make every
    transaction read-only and bound every statement, whatever the query asks for.
    """
    if not _SAFE_PASSWORD.fullmatch(password):
        raise ValueError("The read-only database password must be 16 or more of A-Z a-z 0-9 _ -")
    async with db.session() as session:
        await session.execute(text(f"ALTER ROLE {READONLY_ROLE} LOGIN PASSWORD '{password}'"))
        await session.execute(
            text(f"ALTER ROLE {READONLY_ROLE} SET default_transaction_read_only = on")
        )
        await session.execute(text(f"ALTER ROLE {READONLY_ROLE} SET statement_timeout = '5s'"))
    login = make_url(url).set(username=READONLY_ROLE, password=password)
    return Database(login.render_as_string(hide_password=False))
