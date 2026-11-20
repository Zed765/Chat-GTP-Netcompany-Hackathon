from typing import Any

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from gateway.app.db.base import Base


class DirectoryUser(Base):
    """The identity directory. Events link to it only through the pseudonym key, kept outside
    the database."""

    __tablename__ = "directory_users"

    user_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(200))
    team: Mapped[str] = mapped_column(String(80))
    source: Mapped[str] = mapped_column(String(20))


class DirectoryNetwork(Base):
    """A client address range and the team that sits on it, for logs that carry no user."""

    __tablename__ = "directory_networks"

    cidr: Mapped[str] = mapped_column(String(50), primary_key=True)
    team: Mapped[str] = mapped_column(String(80))
    source: Mapped[str] = mapped_column(String(20))


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)
