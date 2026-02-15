"""Domain model for verified sending domains."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Domain(Base):
    """Represents a verified sending domain."""

    __tablename__ = "domains"

    # Primary key
    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    # Domain name (unique)
    domain: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
    )

    # Verification status
    verification_status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="Pending",
    )

    # DKIM status
    dkim_status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="Pending",
    )

    # Verification token
    verification_token: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    # DKIM tokens (array of 3 tokens)
    dkim_tokens: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
    )

    # Timestamps
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<Domain(domain={self.domain}, status={self.verification_status})>"
