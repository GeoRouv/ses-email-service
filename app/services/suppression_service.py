"""Suppression list management service."""

import logging
from datetime import datetime
from uuid import uuid4

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.suppression import Suppression
from app.schemas.common import raise_api_error
from app.schemas.suppression import AddSuppressionRequest, SuppressionCheckResponse
from app.utils.email_validator import validate_email

logger = logging.getLogger(__name__)


async def get_suppressions(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 25,
    reason: str | None = None,
) -> tuple[list[Suppression], int]:
    """
    Get paginated suppression list with optional reason filter.

    Args:
        db: Database session
        page: Page number (1-indexed)
        page_size: Items per page
        reason: Optional reason filter

    Returns:
        Tuple of (suppression list, total count)
    """
    # Build query
    query = select(Suppression)

    # Apply reason filter if provided
    if reason:
        query = query.where(Suppression.reason == reason)

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Apply pagination
    offset = (page - 1) * page_size
    query = query.order_by(Suppression.created_at.desc()).offset(offset).limit(page_size)

    # Execute query
    result = await db.execute(query)
    suppressions = result.scalars().all()

    return list(suppressions), total


async def add_suppression(
    db: AsyncSession,
    request: AddSuppressionRequest,
) -> Suppression:
    """
    Add email to suppression list.

    Args:
        db: Database session
        request: Add suppression request

    Returns:
        Created suppression record

    Raises:
        HTTPException: If email is invalid or already suppressed
    """
    # Validate email format
    is_valid, error_msg = validate_email(request.email)
    if not is_valid:
        logger.warning(f"Invalid email for suppression: {request.email}")
        raise_api_error(
            code="INVALID_EMAIL",
            message=error_msg or "Invalid email address",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # Check if already suppressed
    existing = await db.execute(
        select(Suppression).where(Suppression.email == request.email.lower())
    )
    if existing.scalar_one_or_none():
        logger.info(f"Email already suppressed: {request.email}")
        raise_api_error(
            code="ALREADY_SUPPRESSED",
            message=f"Email {request.email} is already on the suppression list",
            status_code=status.HTTP_409_CONFLICT,
            details={"email": request.email},
        )

    # Create suppression record
    suppression = Suppression(
        id=uuid4(),
        email=request.email.lower(),
        reason=request.reason,
    )

    try:
        db.add(suppression)
        await db.flush()
        await db.refresh(suppression)

        logger.info(f"Added {request.email} to suppression list (reason: {request.reason})")
        return suppression

    except IntegrityError:
        # Race condition - email was added by another request
        logger.warning(f"Race condition adding suppression: {request.email}")
        raise_api_error(
            code="ALREADY_SUPPRESSED",
            message=f"Email {request.email} is already on the suppression list",
            status_code=status.HTTP_409_CONFLICT,
        )


async def remove_suppression(db: AsyncSession, email: str) -> bool:
    """
    Remove email from suppression list.

    Args:
        db: Database session
        email: Email address to remove

    Returns:
        True if removed, False if not found
    """
    # Find suppression record
    result = await db.execute(
        select(Suppression).where(Suppression.email == email.lower())
    )
    suppression = result.scalar_one_or_none()

    if not suppression:
        logger.info(f"Suppression not found for removal: {email}")
        return False

    # Delete it
    await db.delete(suppression)
    await db.flush()

    logger.info(f"Removed {email} from suppression list")
    return True


async def check_suppression(db: AsyncSession, email: str) -> SuppressionCheckResponse:
    """
    Check if email is suppressed.

    Args:
        db: Database session
        email: Email address to check

    Returns:
        Suppression check response
    """
    # Find suppression record
    result = await db.execute(
        select(Suppression).where(Suppression.email == email.lower())
    )
    suppression = result.scalar_one_or_none()

    if suppression:
        return SuppressionCheckResponse(
            email=email.lower(),
            suppressed=True,
            reason=suppression.reason,
            created_at=suppression.created_at,
        )
    else:
        return SuppressionCheckResponse(
            email=email.lower(),
            suppressed=False,
            reason=None,
            created_at=None,
        )
