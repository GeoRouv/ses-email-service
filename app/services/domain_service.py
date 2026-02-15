"""Domain verification and management service."""

import logging
from datetime import datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import Domain
from app.schemas.domain import DnsRecord
from app.services.ses_client import SESError, ses_client

logger = logging.getLogger(__name__)


async def initiate_verification(db: AsyncSession, domain_name: str) -> Domain:
    """
    Initiate domain verification with SES.

    Calls VerifyDomainIdentity and VerifyDomainDkim, stores results in DB.

    Args:
        db: Database session
        domain_name: Domain to verify

    Returns:
        Domain record with verification details
    """
    domain_name = domain_name.lower().strip()

    # Check if domain already exists in DB
    result = await db.execute(
        select(Domain).where(Domain.domain == domain_name)
    )
    existing = result.scalar_one_or_none()

    if existing:
        logger.info(f"Domain {domain_name} already exists, re-initiating verification")
        # Re-initiate verification with SES
        verification_token = await ses_client.verify_domain(domain_name)
        dkim_tokens = await ses_client.verify_domain_dkim(domain_name)

        existing.verification_token = verification_token
        existing.dkim_tokens = dkim_tokens
        existing.verification_status = "Pending"
        existing.dkim_status = "Pending"

        await db.flush()
        await db.refresh(existing)
        return existing

    # Initiate verification with SES
    verification_token = await ses_client.verify_domain(domain_name)
    dkim_tokens = await ses_client.verify_domain_dkim(domain_name)

    # Store in database
    domain = Domain(
        id=uuid4(),
        domain=domain_name,
        verification_status="Pending",
        dkim_status="Pending",
        verification_token=verification_token,
        dkim_tokens=dkim_tokens,
    )

    db.add(domain)
    await db.flush()
    await db.refresh(domain)

    logger.info(f"Domain verification initiated for {domain_name}")
    return domain


def build_dns_records(domain: Domain) -> list[DnsRecord]:
    """
    Build the list of required DNS records for domain verification.

    Args:
        domain: Domain record with tokens

    Returns:
        List of DNS records to configure
    """
    records = []

    # TXT record for domain verification
    records.append(DnsRecord(
        type="TXT",
        name=f"_amazonses.{domain.domain}",
        value=domain.verification_token,
    ))

    # CNAME records for DKIM (typically 3 tokens)
    for token in domain.dkim_tokens:
        records.append(DnsRecord(
            type="CNAME",
            name=f"{token}._domainkey.{domain.domain}",
            value=f"{token}.dkim.amazonses.com",
        ))

    return records


async def refresh_status(db: AsyncSession, domain_name: str) -> Domain | None:
    """
    Check current verification and DKIM status from SES and update DB.

    Args:
        db: Database session
        domain_name: Domain to check

    Returns:
        Updated domain record, or None if not found
    """
    # Find domain in DB
    result = await db.execute(
        select(Domain).where(Domain.domain == domain_name.lower())
    )
    domain = result.scalar_one_or_none()

    if not domain:
        return None

    # Get latest status from SES
    try:
        verification_attrs = await ses_client.get_domain_verification_status(domain_name)
        verification_status = verification_attrs.get("VerificationStatus", "NotStarted")

        dkim_attrs = await ses_client.get_domain_dkim_status(domain_name)
        dkim_status = "Success" if dkim_attrs.get("DkimVerified", False) else "Pending"

    except SESError as e:
        logger.error(f"Failed to refresh status for {domain_name}: {e}")
        return domain

    # Update DB
    domain.verification_status = verification_status
    domain.dkim_status = dkim_status

    # Set verified_at timestamp when first verified
    if verification_status == "Success" and domain.verified_at is None:
        domain.verified_at = datetime.utcnow()

    await db.flush()
    await db.refresh(domain)

    logger.info(
        f"Domain {domain_name} status: verification={verification_status}, "
        f"dkim={dkim_status}"
    )
    return domain


async def get_domain(db: AsyncSession, domain_name: str) -> Domain | None:
    """
    Get domain record from DB.

    Args:
        db: Database session
        domain_name: Domain to look up

    Returns:
        Domain if found, None otherwise
    """
    result = await db.execute(
        select(Domain).where(Domain.domain == domain_name.lower())
    )
    return result.scalar_one_or_none()


async def list_domains(db: AsyncSession) -> tuple[list[Domain], int]:
    """
    List all domains from DB.

    Args:
        db: Database session

    Returns:
        Tuple of (domain list, total count)
    """
    # Get total count
    count_result = await db.execute(select(func.count()).select_from(Domain))
    total = count_result.scalar() or 0

    # Get all domains
    result = await db.execute(
        select(Domain).order_by(Domain.created_at.desc())
    )
    domains = result.scalars().all()

    return list(domains), total


async def delete_domain(db: AsyncSession, domain_name: str) -> bool:
    """
    Remove domain from local database only.

    Does NOT call SES DeleteIdentity — keeps SES state intact for safety.

    Args:
        db: Database session
        domain_name: Domain to remove

    Returns:
        True if removed, False if not found
    """
    result = await db.execute(
        select(Domain).where(Domain.domain == domain_name.lower())
    )
    domain = result.scalar_one_or_none()

    if not domain:
        return False

    await db.delete(domain)
    await db.flush()

    logger.info(f"Domain {domain_name} removed from local database (SES state preserved)")
    return True


async def is_domain_verified(db: AsyncSession, domain_name: str) -> bool:
    """
    Check if a domain is verified (for send flow enforcement).

    Args:
        db: Database session
        domain_name: Domain to check

    Returns:
        True if domain is verified in our DB
    """
    result = await db.execute(
        select(Domain).where(
            Domain.domain == domain_name.lower(),
            Domain.verification_status == "Success",
        )
    )
    return result.scalar_one_or_none() is not None
