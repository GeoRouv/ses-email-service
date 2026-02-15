"""Email-related Pydantic schemas."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SendEmailRequest(BaseModel):
    """Request schema for sending an email."""

    to_email: str = Field(..., description="Recipient email address")
    from_email: str = Field(..., description="Sender email address")
    from_name: str | None = Field(None, description="Sender display name")
    subject: str = Field(..., min_length=1, max_length=500, description="Email subject")
    html_content: str = Field(..., min_length=1, description="HTML email body")
    text_content: str | None = Field(None, description="Plain text email body (optional)")
    metadata: dict[str, Any] | None = Field(
        None,
        description="Optional metadata to attach to the message",
    )

    @field_validator("to_email", "from_email")
    @classmethod
    def validate_email_format(cls, v: str) -> str:
        """Basic email format validation."""
        if not v or "@" not in v:
            raise ValueError("Invalid email address format")
        return v.strip().lower()

    @field_validator("subject")
    @classmethod
    def validate_subject(cls, v: str) -> str:
        """Validate subject is not empty."""
        if not v.strip():
            raise ValueError("Subject cannot be empty")
        return v.strip()


class SendEmailResponse(BaseModel):
    """Response schema for email sending."""

    model_config = ConfigDict(from_attributes=True)

    success: bool = True
    message_id: UUID = Field(..., description="Internal message ID")
    ses_message_id: str = Field(..., description="SES message ID")
    status: str = Field(..., description="Current message status")
    created_at: datetime = Field(..., description="Message creation timestamp")


class MessageDetail(BaseModel):
    """Detailed message information."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    ses_message_id: str
    to_email: str
    from_email: str
    from_name: str | None
    subject: str
    status: str
    message_metadata: dict[str, Any] | None
    opened_at: datetime | None
    first_deferred_at: datetime | None
    created_at: datetime
    updated_at: datetime


class MessageListItem(BaseModel):
    """Message list item for activity views."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    to_email: str
    from_email: str
    subject: str
    status: str
    created_at: datetime
    opened_at: datetime | None
