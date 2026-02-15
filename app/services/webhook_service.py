"""Webhook processing service for SES events via SNS."""

import json
import logging
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.models.message import Message
from app.models.suppression import Suppression

logger = logging.getLogger(__name__)


async def get_message_by_ses_id(db: AsyncSession, ses_message_id: str) -> Message | None:
    """
    Find message by SES message ID.

    Args:
        db: Database session
        ses_message_id: SES message ID from webhook

    Returns:
        Message if found, None otherwise
    """
    # Strip angle brackets if present
    if ses_message_id.startswith("<") and ses_message_id.endswith(">"):
        ses_message_id = ses_message_id[1:-1]

    result = await db.execute(
        select(Message).where(Message.ses_message_id == ses_message_id)
    )
    return result.scalar_one_or_none()


async def handle_delivery(db: AsyncSession, event: dict[str, Any]) -> None:
    """
    Handle SES Delivery event.

    Updates message status to 'delivered'.

    Args:
        db: Database session
        event: SES delivery event payload
    """
    ses_message_id = event["mail"]["messageId"]
    delivery_timestamp = event["delivery"]["timestamp"]

    logger.info(f"Processing Delivery event for {ses_message_id}")

    # Find message
    message = await get_message_by_ses_id(db, ses_message_id)
    if not message:
        logger.warning(f"Message not found for SES ID: {ses_message_id}")
        return

    # Update status (only if current status allows transition)
    valid_transitions = {"sent", "deferred"}
    if message.status in valid_transitions:
        message.status = "delivered"
        message.updated_at = datetime.utcnow()
        logger.info(f"Message {message.id} marked as delivered")
    else:
        logger.warning(
            f"Ignoring delivery event for message {message.id} "
            f"in status {message.status}"
        )

    # Store event
    event_record = Event(
        id=uuid4(),
        message_id=message.id,
        event_type="delivery",
        raw_payload=event,
        timestamp=datetime.fromisoformat(delivery_timestamp.replace("Z", "+00:00")),
    )
    db.add(event_record)

    await db.flush()


async def handle_bounce(db: AsyncSession, event: dict[str, Any]) -> None:
    """
    Handle SES Bounce event.

    Updates message status to 'bounced' and auto-suppresses on hard bounce.

    Args:
        db: Database session
        event: SES bounce event payload
    """
    ses_message_id = event["mail"]["messageId"]
    bounce = event["bounce"]
    bounce_type = bounce["bounceType"]  # "Permanent" or "Transient"
    bounced_recipients = bounce.get("bouncedRecipients", [])

    logger.info(f"Processing Bounce event ({bounce_type}) for {ses_message_id}")

    # Find message
    message = await get_message_by_ses_id(db, ses_message_id)
    if not message:
        logger.warning(f"Message not found for SES ID: {ses_message_id}")
        return

    # Map SES bounce type to our format
    bounce_type_mapped = "hard" if bounce_type == "Permanent" else "soft"

    # Get bounce reason
    bounce_reason = None
    if bounced_recipients:
        bounce_reason = bounced_recipients[0].get("diagnosticCode", "Unknown")

    # Update status
    message.status = "bounced"
    message.updated_at = datetime.utcnow()

    # Store event
    event_record = Event(
        id=uuid4(),
        message_id=message.id,
        event_type="bounce",
        bounce_type=bounce_type_mapped,
        bounce_reason=bounce_reason,
        raw_payload=event,
        timestamp=datetime.fromisoformat(bounce["timestamp"].replace("Z", "+00:00")),
    )
    db.add(event_record)

    # Auto-suppress on hard bounce
    if bounce_type_mapped == "hard":
        await add_to_suppression_list(
            db,
            message.to_email,
            reason="hard_bounce",
        )
        logger.info(f"Auto-suppressed {message.to_email} due to hard bounce")

    await db.flush()


async def handle_complaint(db: AsyncSession, event: dict[str, Any]) -> None:
    """
    Handle SES Complaint event.

    Updates message status to 'complained' and auto-suppresses the recipient.

    Args:
        db: Database session
        event: SES complaint event payload
    """
    ses_message_id = event["mail"]["messageId"]
    complaint = event["complaint"]

    logger.info(f"Processing Complaint event for {ses_message_id}")

    # Find message
    message = await get_message_by_ses_id(db, ses_message_id)
    if not message:
        logger.warning(f"Message not found for SES ID: {ses_message_id}")
        return

    # Update status (complaints can come after delivery)
    message.status = "complained"
    message.updated_at = datetime.utcnow()

    # Store event
    event_record = Event(
        id=uuid4(),
        message_id=message.id,
        event_type="complaint",
        raw_payload=event,
        timestamp=datetime.fromisoformat(complaint["timestamp"].replace("Z", "+00:00")),
    )
    db.add(event_record)

    # Auto-suppress on complaint
    await add_to_suppression_list(
        db,
        message.to_email,
        reason="complaint",
    )
    logger.info(f"Auto-suppressed {message.to_email} due to complaint")

    await db.flush()


async def handle_delivery_delay(db: AsyncSession, event: dict[str, Any]) -> None:
    """
    Handle SES DeliveryDelay event.

    Updates message status to 'deferred' and tracks first deferral time.

    Args:
        db: Database session
        event: SES delivery delay event payload
    """
    ses_message_id = event["mail"]["messageId"]
    delay = event["deliveryDelay"]
    delay_type = delay.get("delayType", "Unknown")

    logger.info(f"Processing DeliveryDelay event ({delay_type}) for {ses_message_id}")

    # Find message
    message = await get_message_by_ses_id(db, ses_message_id)
    if not message:
        logger.warning(f"Message not found for SES ID: {ses_message_id}")
        return

    # Get delay reason
    delay_reason = None
    delayed_recipients = delay.get("delayedRecipients", [])
    if delayed_recipients:
        delay_reason = delayed_recipients[0].get("diagnosticCode", "Unknown")

    # Update status to deferred (if currently sent)
    if message.status == "sent":
        message.status = "deferred"

        # Set first_deferred_at if not already set
        if message.first_deferred_at is None:
            message.first_deferred_at = datetime.utcnow()
            logger.info(f"Message {message.id} first deferred at {message.first_deferred_at}")

    message.updated_at = datetime.utcnow()

    # Store event
    event_record = Event(
        id=uuid4(),
        message_id=message.id,
        event_type="delay",
        delay_type=delay_type,
        delay_reason=delay_reason,
        raw_payload=event,
        timestamp=datetime.fromisoformat(delay["timestamp"].replace("Z", "+00:00")),
    )
    db.add(event_record)

    await db.flush()


async def handle_reject(db: AsyncSession, event: dict[str, Any]) -> None:
    """
    Handle SES Reject event.

    Updates message status to 'rejected'.

    Args:
        db: Database session
        event: SES reject event payload
    """
    ses_message_id = event["mail"]["messageId"]

    logger.info(f"Processing Reject event for {ses_message_id}")

    # Find message
    message = await get_message_by_ses_id(db, ses_message_id)
    if not message:
        logger.warning(f"Message not found for SES ID: {ses_message_id}")
        return

    # Update status to rejected (terminal state)
    message.status = "rejected"
    message.updated_at = datetime.utcnow()

    # Store event
    event_record = Event(
        id=uuid4(),
        message_id=message.id,
        event_type="reject",
        raw_payload=event,
        timestamp=datetime.fromisoformat(event["reject"]["timestamp"].replace("Z", "+00:00")),
    )
    db.add(event_record)

    await db.flush()


async def add_to_suppression_list(
    db: AsyncSession,
    email: str,
    reason: str,
) -> None:
    """
    Add email to suppression list (idempotent).

    Args:
        db: Database session
        email: Email address to suppress
        reason: Suppression reason
    """
    # Check if already suppressed
    result = await db.execute(
        select(Suppression).where(Suppression.email == email.lower())
    )
    existing = result.scalar_one_or_none()

    if existing:
        logger.debug(f"Email {email} already suppressed")
        return

    # Add to suppression list
    suppression = Suppression(
        id=uuid4(),
        email=email.lower(),
        reason=reason,
    )
    db.add(suppression)
    logger.info(f"Added {email} to suppression list (reason: {reason})")


async def process_ses_event(db: AsyncSession, ses_event: dict[str, Any]) -> None:
    """
    Route SES event to appropriate handler.

    Args:
        db: Database session
        ses_event: Parsed SES event from SNS Message field
    """
    event_type = ses_event.get("eventType")

    if not event_type:
        logger.error("SES event missing eventType field")
        return

    # Route to handler
    handlers = {
        "Delivery": handle_delivery,
        "Bounce": handle_bounce,
        "Complaint": handle_complaint,
        "DeliveryDelay": handle_delivery_delay,
        "Reject": handle_reject,
    }

    handler = handlers.get(event_type)
    if handler:
        await handler(db, ses_event)
    else:
        logger.warning(f"Unknown SES event type: {event_type}")
