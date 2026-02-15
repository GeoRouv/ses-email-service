"""Domain-related Pydantic schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class VerifyDomainRequest(BaseModel):
    """Request schema for initiating domain verification."""

    domain: str = Field(..., description="Domain name to verify (e.g., example.com)")

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, v: str) -> str:
        """Validate domain format."""
        v = v.strip().lower()
        if not v or "." not in v:
            raise ValueError("Invalid domain format")
        if "@" in v:
            raise ValueError("Provide a domain, not an email address")
        return v


class DnsRecord(BaseModel):
    """A single DNS record required for verification."""

    type: str = Field(..., description="DNS record type (TXT or CNAME)")
    name: str = Field(..., description="DNS record name/host")
    value: str = Field(..., description="DNS record value")


class DomainItem(BaseModel):
    """Domain list item."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    domain: str
    verification_status: str
    dkim_status: str
    verified_at: datetime | None
    created_at: datetime


class DomainVerifyResponse(BaseModel):
    """Response for domain verification initiation."""

    domain: str
    verification_status: str
    dkim_status: str
    dns_records: list[DnsRecord]
    message: str


class DomainRecordsResponse(BaseModel):
    """Response for domain DNS records."""

    domain: str
    dns_records: list[DnsRecord]


class DomainStatusResponse(BaseModel):
    """Response for domain verification status check."""

    domain: str
    verification_status: str
    dkim_status: str
    verified_at: datetime | None
    created_at: datetime


class DomainListResponse(BaseModel):
    """Response for domain list endpoint."""

    items: list[DomainItem]
    total: int
