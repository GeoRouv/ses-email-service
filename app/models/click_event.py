"""Click event model for tracking link clicks."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ClickEvent(Base):
    """Represents a link click event."""

    __tablename__ = "click_events"

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

    # URL that was clicked
    url: Mapped[str] = mapped_column(Text, nullable=False)

    # Timestamp
    clicked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    message: Mapped["Message"] = relationship("Message", back_populates="click_events")

    # Note: index for message_id is defined via index=True on the column above.

    def __repr__(self) -> str:
        return f"<ClickEvent(id={self.id}, message_id={self.message_id}, url={self.url[:50]})>"
