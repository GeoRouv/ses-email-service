"""Event model for SES webhook events."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Event(Base):
    """Represents an SES event (delivery, bounce, complaint, delay, reject)."""

    __tablename__ = "events"

    # Primary key
    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    # Foreign key to message
    message_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # Event details
    event_type: Mapped[str] = mapped_column(
        String(50),
        index=True,
        nullable=False,
    )

    # Bounce-specific fields
    bounce_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    bounce_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Delay-specific fields
    delay_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    delay_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Raw payload from SES
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # Timestamps
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    message: Mapped["Message"] = relationship("Message", back_populates="events")

    # Indexes
    __table_args__ = (
        Index("ix_events_message_id", "message_id"),
        Index("ix_events_event_type", "event_type"),
    )

    def __repr__(self) -> str:
        return f"<Event(id={self.id}, type={self.event_type}, message_id={self.message_id})>"
