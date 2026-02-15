"""Domain verification API routes."""

import logging

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.schemas.common import raise_api_error
from app.schemas.domain import (
    DomainListResponse,
    DomainRecordsResponse,
    DomainStatusResponse,
    DomainVerifyResponse,
    VerifyDomainRequest,
)
from app.services import domain_service
from app.services.ses_client import SESError

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/domains/verify",
    response_model=DomainVerifyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def verify_domain(
    request: VerifyDomainRequest,
    db: AsyncSession = Depends(get_session),
) -> DomainVerifyResponse:
    """
    Initiate domain verification with AWS SES.

    Calls VerifyDomainIdentity and VerifyDomainDkim to start the
    verification process. Returns the DNS records that must be
    configured to complete verification.

    **Request Body:**
    ```json
    { "domain": "example.com" }
    ```

    **Response:**
    - DNS records to configure (TXT for verification, CNAME for DKIM)
    - Current verification status (initially "Pending")

    **DNS Records Required:**
    1. TXT record at `_amazonses.example.com` with verification token
    2. Three CNAME records for DKIM signing

    **Re-verification:**
    If the domain already exists, verification is re-initiated and
    tokens are refreshed.
    """
    try:
        domain = await domain_service.initiate_verification(db, request.domain)
    except SESError as e:
        logger.error(f"SES error verifying domain {request.domain}: {e}")
        raise_api_error(
            code="DOMAIN_VERIFICATION_FAILED",
            message=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    dns_records = domain_service.build_dns_records(domain)

    return DomainVerifyResponse(
        domain=domain.domain,
        verification_status=domain.verification_status,
        dkim_status=domain.dkim_status,
        dns_records=dns_records,
        message="Configure the DNS records below to complete verification",
    )


@router.get("/domains/{domain}/records", response_model=DomainRecordsResponse)
async def get_domain_records(
    domain: str,
    db: AsyncSession = Depends(get_session),
) -> DomainRecordsResponse:
    """
    Get required DNS records for a domain.

    Returns the TXT and CNAME records that must be configured
    in the domain's DNS to complete verification.

    **Path Parameter:**
    - `domain`: Domain name (e.g., example.com)

    **Response:**
    - List of DNS records with type, name, and value

    **Example DNS configuration:**
    ```
    _amazonses.example.com  TXT  "verification-token-value"
    token1._domainkey.example.com  CNAME  token1.dkim.amazonses.com
    token2._domainkey.example.com  CNAME  token2.dkim.amazonses.com
    token3._domainkey.example.com  CNAME  token3.dkim.amazonses.com
    ```
    """
    domain_record = await domain_service.get_domain(db, domain)

    if not domain_record:
        raise_api_error(
            code="DOMAIN_NOT_FOUND",
            message=f"Domain {domain} not found",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    dns_records = domain_service.build_dns_records(domain_record)

    return DomainRecordsResponse(
        domain=domain_record.domain,
        dns_records=dns_records,
    )


@router.get("/domains/{domain}/status", response_model=DomainStatusResponse)
async def get_domain_status(
    domain: str,
    db: AsyncSession = Depends(get_session),
) -> DomainStatusResponse:
    """
    Check current verification and DKIM status from SES.

    Queries SES for the latest status and updates the local database.

    **Path Parameter:**
    - `domain`: Domain name (e.g., example.com)

    **Verification Statuses:**
    - `Pending`: Waiting for DNS records to be configured
    - `Success`: Domain is verified and ready for sending
    - `Failed`: Verification failed
    - `TemporaryFailure`: Temporary failure, will retry
    - `NotStarted`: Verification not initiated

    **DKIM Statuses:**
    - `Pending`: Waiting for DKIM CNAME records
    - `Success`: DKIM is verified and active
    """
    domain_record = await domain_service.refresh_status(db, domain)

    if not domain_record:
        raise_api_error(
            code="DOMAIN_NOT_FOUND",
            message=f"Domain {domain} not found",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return DomainStatusResponse(
        domain=domain_record.domain,
        verification_status=domain_record.verification_status,
        dkim_status=domain_record.dkim_status,
        verified_at=domain_record.verified_at,
        created_at=domain_record.created_at,
    )


@router.get("/domains", response_model=DomainListResponse)
async def list_domains(
    db: AsyncSession = Depends(get_session),
) -> DomainListResponse:
    """
    List all domains in the local database.

    Returns all domains with their current verification status.
    Note: statuses reflect the last known state. Use the
    `/domains/{domain}/status` endpoint for real-time SES status.
    """
    domains, total = await domain_service.list_domains(db)

    return DomainListResponse(
        items=domains,
        total=total,
    )


@router.delete("/domains/{domain}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_domain(
    domain: str,
    db: AsyncSession = Depends(get_session),
) -> Response:
    """
    Remove domain from local database.

    **Important:** This only removes the domain from the local database.
    It does NOT call SES DeleteIdentity, so the domain remains verified
    in SES. This is intentional — removing from SES could break other
    services using the same domain.

    **Path Parameter:**
    - `domain`: Domain name to remove

    **Response:**
    - 204 No Content: Domain removed from local database
    - 404 Not Found: Domain not in database
    """
    removed = await domain_service.delete_domain(db, domain)

    if not removed:
        return Response(status_code=status.HTTP_404_NOT_FOUND)

    return Response(status_code=status.HTTP_204_NO_CONTENT)
