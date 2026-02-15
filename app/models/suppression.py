"""Suppression model for email suppression list."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Suppression(Base):
    """Represents a suppressed email address."""

    __tablename__ = "suppressions"

    # Primary key
    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    # Email address (unique)
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )

    # Reason for suppression
    reason: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Indexes
    __table_args__ = (Index("ix_suppressions_email", "email", unique=True),)

    def __repr__(self) -> str:
        return f"<Suppression(email={self.email}, reason={self.reason})>"
