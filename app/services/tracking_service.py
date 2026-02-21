"""Tracking service for email opens and clicks."""

import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.click_event import ClickEvent
from app.models.message import Message

logger = logging.getLogger(__name__)


async def get_message_by_id(db: AsyncSession, message_id: UUID | str) -> Message | None:
    """
    Get message by ID.

    Args:
        db: Database session
        message_id: Message UUID or string

    Returns:
        Message if found, None otherwise
    """
    if isinstance(message_id, str):
        try:
            message_id = UUID(message_id)
        except ValueError:
            logger.warning(f"Invalid message ID format: {message_id}")
            return None

    result = await db.execute(select(Message).where(Message.id == message_id))
    return result.scalar_one_or_none()


async def record_open(db: AsyncSession, message_id: str) -> bool:
    """
    Record email open event.

    Only records the FIRST open. Subsequent opens are ignored.

    Args:
        db: Database session
        message_id: Message ID (UUID string)

    Returns:
        True if open was recorded, False if already opened or message not found
    """
    message = await get_message_by_id(db, message_id)

    if not message:
        logger.warning(f"Message not found for open tracking: {message_id}")
        return False

    # Only record first open
    if message.opened_at is not None:
        logger.debug(f"Message {message_id} already opened at {message.opened_at}")
        return False

    # Record open timestamp
    message.opened_at = datetime.now(timezone.utc)
    message.updated_at = datetime.now(timezone.utc)

    await db.flush()

    logger.info(f"Recorded open for message {message_id}")
    return True


async def record_click(db: AsyncSession, message_id: str, url: str) -> bool:
    """
    Record email click event.

    Records ALL clicks (not just first) for analytics.

    Args:
        db: Database session
        message_id: Message ID (UUID string)
        url: URL that was clicked

    Returns:
        True if click was recorded, False if message not found
    """
    message = await get_message_by_id(db, message_id)

    if not message:
        logger.warning(f"Message not found for click tracking: {message_id}")
        return False

    # Create click event
    click_event = ClickEvent(
        id=uuid4(),
        message_id=message.id,
        url=url,
        clicked_at=datetime.now(timezone.utc),
    )

    db.add(click_event)
    await db.flush()

    logger.info(f"Recorded click for message {message_id}: {url[:100]}")
    return True


async def get_click_count(db: AsyncSession, message_id: UUID) -> int:
    """
    Get total click count for a message.

    Args:
        db: Database session
        message_id: Message ID

    Returns:
        Number of clicks
    """
    result = await db.execute(select(ClickEvent).where(ClickEvent.message_id == message_id))
    clicks = result.scalars().all()
    return len(clicks)


async def get_unique_click_count(db: AsyncSession, message_id: UUID) -> int:
    """
    Get unique click count (distinct URLs) for a message.

    Args:
        db: Database session
        message_id: Message ID

    Returns:
        Number of unique URLs clicked
    """
    result = await db.execute(
        select(ClickEvent.url).where(ClickEvent.message_id == message_id).distinct()
    )
    unique_urls = result.scalars().all()
    return len(unique_urls)
