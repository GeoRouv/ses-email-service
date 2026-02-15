"""Message model for email records."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Message(Base):
    """Represents an email message sent through the system."""

    __tablename__ = "messages"

    # Primary key
    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    # SES correlation
    ses_message_id: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )

    # Email details
    to_email: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    from_email: Mapped[str] = mapped_column(String(255), nullable=False)
    from_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    html_content: Mapped[str] = mapped_column(Text, nullable=False)
    text_content: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Status tracking
    status: Mapped[str] = mapped_column(
        String(50),
        index=True,
        nullable=False,
        default="sent",
    )

    # Metadata (renamed to avoid SQLAlchemy reserved name)
    message_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Tracking timestamps
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_deferred_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Audit timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    events: Mapped[list["Event"]] = relationship(
        "Event",
        back_populates="message",
        cascade="all, delete-orphan",
    )
    click_events: Mapped[list["ClickEvent"]] = relationship(
        "ClickEvent",
        back_populates="message",
        cascade="all, delete-orphan",
    )

    # Note: indexes for to_email, status, created_at are defined via
    # index=True on their respective column definitions above.

    def __repr__(self) -> str:
        return f"<Message(id={self.id}, to={self.to_email}, status={self.status})>"
