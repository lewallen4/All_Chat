"""
All_Chat — Persistent Audit Log
All admin actions written to DB. Never lost on restart.
"""
from datetime import datetime, timezone
from sqlalchemy import Integer, String, Text, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column
from core.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id:         Mapped[int]           = mapped_column(Integer, primary_key=True, index=True)
    timestamp:  Mapped[datetime]      = mapped_column(DateTime(timezone=True),
                                                       default=lambda: datetime.now(timezone.utc),
                                                       index=True)
    admin:      Mapped[str]           = mapped_column(String(32), nullable=False, index=True)
    action:     Mapped[str]           = mapped_column(String(64), nullable=False)
    target:     Mapped[str]           = mapped_column(String(128), nullable=False)
    detail:     Mapped[str | None]    = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None]    = mapped_column(String(45), nullable=True)

    __table_args__ = (
        Index("ix_audit_timestamp", "timestamp"),
        Index("ix_audit_admin",     "admin"),
    )
