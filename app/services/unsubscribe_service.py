"""Unsubscribe service for JWT token generation, validation, and processing."""

import logging
from datetime import datetime, timedelta
from uuid import uuid4

import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.suppression import Suppression

logger = logging.getLogger(__name__)


def generate_unsubscribe_token(email: str, message_id: str) -> str:
    """
    Generate a signed JWT token for unsubscribe links.

    Args:
        email: Recipient email address
        message_id: Message UUID string

    Returns:
        JWT token string
    """
    payload = {
        "email": email,
        "message_id": message_id,
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(days=30),
    }
    return jwt.encode(payload, settings.UNSUBSCRIBE_SECRET, algorithm="HS256")


def validate_unsubscribe_token(token: str) -> dict | None:
    """
    Validate and decode an unsubscribe JWT token.

    Args:
        token: JWT token string

    Returns:
        Decoded payload dict if valid, None if invalid/expired
    """
    try:
        return jwt.decode(
            token,
            settings.UNSUBSCRIBE_SECRET,
            algorithms=["HS256"],
        )
    except jwt.ExpiredSignatureError:
        logger.warning("Unsubscribe token expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid unsubscribe token: {e}")
        return None


def build_unsubscribe_url(email: str, message_id: str) -> str:
    """
    Build a full unsubscribe URL with signed token.

    Args:
        email: Recipient email address
        message_id: Message UUID string

    Returns:
        Full unsubscribe URL
    """
    token = generate_unsubscribe_token(email, message_id)
    return f"{settings.APP_BASE_URL}/unsubscribe/{token}"


async def process_unsubscribe(db: AsyncSession, email: str) -> bool:
    """
    Process an unsubscribe request by adding to suppression list.

    Idempotent — returns True even if already suppressed (double-submit prevention).

    Args:
        db: Database session
        email: Email address to unsubscribe

    Returns:
        True if unsubscribed (or already was), False on error
    """
    email_lower = email.lower()

    # Check if already suppressed (double-submit prevention)
    result = await db.execute(
        select(Suppression).where(Suppression.email == email_lower)
    )
    existing = result.scalar_one_or_none()

    if existing:
        logger.info(f"Email {email} already unsubscribed")
        return True

    # Add to suppression list
    suppression = Suppression(
        id=uuid4(),
        email=email_lower,
        reason="unsubscribe",
    )
    db.add(suppression)
    await db.flush()

    logger.info(f"Email {email} unsubscribed successfully")
    return True
