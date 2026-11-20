"""Who works where. Resolves a user or a client address to a team, and finds the
person behind a pseudonym by recomputing it for every directory entry."""

from ipaddress import IPv4Network, IPv6Network, ip_address, ip_network
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from gateway.app.core.auth import DEMO_USERS
from gateway.app.db.session import Database
from gateway.app.events.writer import pseudonym
from gateway.app.privacy.models import DirectoryNetwork, DirectoryUser

UNKNOWN_TEAM = "Unknown"
DirectorySource = Literal["uploaded", "seeded"]


class DirectoryUserIn(BaseModel):
    user_id: str = Field(min_length=1, max_length=120)
    display_name: str = Field(min_length=1, max_length=200)
    team: str = Field(min_length=1, max_length=80)


class NetworkIn(BaseModel):
    cidr: str = Field(description="For example `10.20.3.0/24`")
    team: str = Field(min_length=1, max_length=80)


class DirectoryImport(BaseModel):
    users: list[DirectoryUserIn] = Field(default_factory=list)
    networks: list[NetworkIn] = Field(default_factory=list)


class Directory:
    def __init__(self, db: Database, pseudonym_key: bytes) -> None:
        self._db = db
        self._key = pseudonym_key
        self._users: dict[str, DirectoryUserIn] = {}
        self._by_pseudonym: dict[str, DirectoryUserIn] = {}
        self._networks: list[tuple[IPv4Network | IPv6Network, str]] = []

    async def reload(self) -> None:
        async with self._db.session() as session:
            users = (await session.execute(select(DirectoryUser))).scalars().all()
            networks = (await session.execute(select(DirectoryNetwork))).scalars().all()
        entries = [
            DirectoryUserIn(user_id=u.user_id, display_name=u.display_name, team=u.team)
            for u in DEMO_USERS
        ]
        entries += [
            DirectoryUserIn(user_id=u.user_id, display_name=u.display_name, team=u.team)
            for u in users
        ]
        self._users = {entry.user_id: entry for entry in entries}
        self._by_pseudonym = {pseudonym(entry.user_id, self._key): entry for entry in entries}
        self._networks = [(ip_network(n.cidr), n.team) for n in networks]

    async def replace(self, source: DirectorySource, data: DirectoryImport) -> None:
        """Swap every entry from `source` for the given ones."""
        for network in data.networks:
            ip_network(network.cidr)
        async with self._db.session() as session:
            await session.execute(delete(DirectoryUser).where(DirectoryUser.source == source))
            await session.execute(delete(DirectoryNetwork).where(DirectoryNetwork.source == source))
            session.add_all(
                DirectoryUser(
                    user_id=u.user_id, display_name=u.display_name, team=u.team, source=source
                )
                for u in data.users
            )
            session.add_all(
                DirectoryNetwork(cidr=n.cidr, team=n.team, source=source) for n in data.networks
            )

    def team_of(self, *, user_id: str | None = None, ip: str | None = None) -> str:
        """The team of a user, or failing that of a client address; else `Unknown`."""
        if user_id and (user := self._users.get(user_id)):
            return user.team
        if ip:
            address = ip_address(ip)
            for network, team in self._networks:
                if address in network:
                    return team
        return UNKNOWN_TEAM

    def find_by_pseudonym(self, user_pseudonym: str) -> DirectoryUserIn | None:
        return self._by_pseudonym.get(user_pseudonym)

    def teams(self) -> list[str]:
        return sorted({user.team for user in self._users.values()})
