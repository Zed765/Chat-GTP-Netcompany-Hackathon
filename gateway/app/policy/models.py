from datetime import datetime

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from gateway.app.db.base import Base, created_at


class PolicyVersion(Base):
    """Every saved policy. Exactly one row is active."""

    __tablename__ = "policy_versions"

    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    yaml: Mapped[str] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(String(300))
    author: Mapped[str] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created: Mapped[datetime] = created_at()
