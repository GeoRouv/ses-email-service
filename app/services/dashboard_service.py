"""Dashboard metrics and analytics service."""

import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import cast, func, select, Date
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.click_event import ClickEvent
from app.models.event import Event
from app.models.message import Message

logger = logging.getLogger(__name__)


async def get_dashboard_metrics(
    db: AsyncSession,
    days: int = 7,
) -> dict[str, Any]:
    """
    Get dashboard metrics for the specified time period.

    Args:
        db: Database session
        days: Number of days to look back

    Returns:
        Dictionary with all dashboard metrics
    """
    since = datetime.utcnow() - timedelta(days=days)

    # Total sent
    total_sent = await db.scalar(
        select(func.count()).select_from(Message).where(
            Message.created_at >= since,
        )
    ) or 0

    # Delivered count
    delivered = await db.scalar(
        select(func.count()).select_from(Message).where(
            Message.created_at >= since,
            Message.status == "delivered",
        )
    ) or 0

    # Bounced count
    bounced = await db.scalar(
        select(func.count()).select_from(Message).where(
            Message.created_at >= since,
            Message.status == "bounced",
        )
    ) or 0

    # Opened count
    opened = await db.scalar(
        select(func.count()).select_from(Message).where(
            Message.created_at >= since,
            Message.opened_at.isnot(None),
        )
    ) or 0

    # Deferred count
    deferred = await db.scalar(
        select(func.count()).select_from(Message).where(
            Message.created_at >= since,
            Message.status == "deferred",
        )
    ) or 0

    # Complained count
    complained = await db.scalar(
        select(func.count()).select_from(Message).where(
            Message.created_at >= since,
            Message.status == "complained",
        )
    ) or 0

    # Click count (unique messages with clicks)
    clicked_messages = await db.scalar(
        select(func.count(func.distinct(ClickEvent.message_id))).where(
            ClickEvent.clicked_at >= since,
        )
    ) or 0

    # Calculate rates (use total_sent as denominator for all rates
    # so metrics work even before delivery webhooks are processed)
    delivery_rate = round(delivered / total_sent * 100, 1) if total_sent else 0
    open_rate = round(opened / total_sent * 100, 1) if total_sent else 0
    click_rate = round(clicked_messages / total_sent * 100, 1) if total_sent else 0
    bounce_rate = round(bounced / total_sent * 100, 1) if total_sent else 0

    return {
        "total_sent": total_sent,
        "delivered": delivered,
        "bounced": bounced,
        "opened": opened,
        "deferred": deferred,
        "complained": complained,
        "clicked_messages": clicked_messages,
        "delivery_rate": delivery_rate,
        "open_rate": open_rate,
        "click_rate": click_rate,
        "bounce_rate": bounce_rate,
        "days": days,
    }


async def get_daily_volume(
    db: AsyncSession,
    days: int = 7,
) -> dict[str, Any]:
    """
    Get daily email volume breakdown for chart data.

    Args:
        db: Database session
        days: Number of days to look back

    Returns:
        Dictionary with labels and datasets for Chart.js
    """
    since = datetime.utcnow() - timedelta(days=days)

    # Query daily counts by status
    result = await db.execute(
        select(
            cast(Message.created_at, Date).label("day"),
            func.count().filter(
                Message.status.in_(["sent", "delivered"])
            ).label("delivered"),
            func.count().filter(
                Message.status == "bounced"
            ).label("bounced"),
            func.count().filter(
                Message.status == "deferred"
            ).label("deferred"),
        )
        .where(Message.created_at >= since)
        .group_by(cast(Message.created_at, Date))
        .order_by(cast(Message.created_at, Date))
    )
    rows = result.all()

    # Build complete date range (fill missing days with 0)
    labels = []
    delivered_counts = []
    bounced_counts = []
    deferred_counts = []

    row_map = {str(row.day): row for row in rows}

    for i in range(days):
        day = (datetime.utcnow() - timedelta(days=days - 1 - i)).date()
        day_str = str(day)
        labels.append(day.strftime("%b %d"))

        if day_str in row_map:
            row = row_map[day_str]
            delivered_counts.append(row.delivered or 0)
            bounced_counts.append(row.bounced or 0)
            deferred_counts.append(row.deferred or 0)
        else:
            delivered_counts.append(0)
            bounced_counts.append(0)
            deferred_counts.append(0)

    return {
        "labels": labels,
        "delivered": delivered_counts,
        "bounced": bounced_counts,
        "deferred": deferred_counts,
    }


async def get_activity_list(
    db: AsyncSession,
    page: int = 1,
    per_page: int = 25,
    status_filter: str | None = None,
) -> dict[str, Any]:
    """
    Get paginated activity list of messages.

    Args:
        db: Database session
        page: Page number (1-based)
        per_page: Items per page
        status_filter: Optional status to filter by

    Returns:
        Dictionary with items, total, page, pages, per_page
    """
    # Base query
    query = select(Message)
    count_query = select(func.count()).select_from(Message)

    if status_filter:
        query = query.where(Message.status == status_filter)
        count_query = count_query.where(Message.status == status_filter)

    # Get total count
    total = await db.scalar(count_query) or 0

    # Get paginated results
    offset = (page - 1) * per_page
    result = await db.execute(
        query.order_by(Message.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    messages = result.scalars().all()

    pages = max(1, -(-total // per_page))  # Ceiling division

    return {
        "messages": messages,
        "total": total,
        "page": page,
        "pages": pages,
        "per_page": per_page,
        "status_filter": status_filter,
    }


async def get_message_detail(
    db: AsyncSession,
    message_id: UUID,
) -> dict[str, Any] | None:
    """
    Get full message detail with events and click events.

    Args:
        db: Database session
        message_id: Message UUID

    Returns:
        Dictionary with message, events, and click_events, or None
    """
    result = await db.execute(
        select(Message)
        .where(Message.id == message_id)
        .options(
            selectinload(Message.events),
            selectinload(Message.click_events),
        )
    )
    message = result.scalar_one_or_none()

    if not message:
        return None

    # Sort events by timestamp descending
    events = sorted(message.events, key=lambda e: e.timestamp, reverse=True)
    click_events = sorted(message.click_events, key=lambda e: e.clicked_at, reverse=True)

    return {
        "message": message,
        "events": events,
        "click_events": click_events,
    }


async def get_deferred_messages(
    db: AsyncSession,
) -> tuple[list[dict[str, Any]], int]:
    """
    Get all currently deferred messages with their latest delay info.

    Returns:
        Tuple of (enriched message list, total count)
    """
    # Get deferred messages with their events
    result = await db.execute(
        select(Message)
        .where(Message.status == "deferred")
        .options(selectinload(Message.events))
        .order_by(Message.first_deferred_at.desc().nullslast())
    )
    messages = result.scalars().all()

    # Enrich with latest delay info
    enriched = []
    for msg in messages:
        # Find the latest delay event
        delay_events = [e for e in msg.events if e.event_type == "delay"]
        latest_delay = max(delay_events, key=lambda e: e.timestamp) if delay_events else None

        enriched.append({
            "id": msg.id,
            "to_email": msg.to_email,
            "from_email": msg.from_email,
            "subject": msg.subject,
            "first_deferred_at": msg.first_deferred_at,
            "created_at": msg.created_at,
            "delay_type": latest_delay.delay_type if latest_delay else None,
            "delay_reason": latest_delay.delay_reason if latest_delay else None,
        })

    return enriched, len(enriched)
