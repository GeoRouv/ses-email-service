"""Suppression-related Pydantic schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AddSuppressionRequest(BaseModel):
    """Request schema for adding an email to suppression list."""

    email: str = Field(..., description="Email address to suppress")
    reason: str = Field(
        ...,
        description="Suppression reason (hard_bounce, complaint, unsubscribe, manual)",
    )

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, v: str) -> str:
        """Validate email format."""
        if not v or "@" not in v:
            raise ValueError("Invalid email address format")
        return v.strip().lower()

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str) -> str:
        """Validate reason is not empty."""
        if not v.strip():
            raise ValueError("Reason cannot be empty")
        return v.strip()


class SuppressionItem(BaseModel):
    """Suppression list item."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    reason: str
    created_at: datetime


class SuppressionCheckResponse(BaseModel):
    """Response for suppression check endpoint."""

    email: str
    suppressed: bool
    reason: str | None = None
    created_at: datetime | None = None


class SuppressionListResponse(BaseModel):
    """Response for suppression list endpoint."""

    items: list[SuppressionItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class SuppressionAddResponse(BaseModel):
    """Response for adding to suppression list."""

    success: bool = True
    email: str
    reason: str
    created_at: datetime
