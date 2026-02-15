"""Tests for webhook processing service."""

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.models.message import Message
from app.models.suppression import Suppression
from app.services.webhook_service import (
    add_to_suppression_list,
    get_message_by_ses_id,
    handle_bounce,
    handle_complaint,
    handle_delivery,
    handle_delivery_delay,
    handle_reject,
    process_ses_event,
)


async def create_test_message(
    db: AsyncSession,
    ses_message_id: str = "test-ses-123",
    status: str = "sent",
    to_email: str = "recipient@example.com",
) -> Message:
    """Helper to create a test message."""
    msg = Message(
        id=uuid4(),
        ses_message_id=ses_message_id,
        to_email=to_email,
        from_email="sender@test.example.com",
        subject="Test Subject",
        html_content="<p>Test</p>",
        status=status,
    )
    db.add(msg)
    await db.flush()
    return msg


class TestGetMessageBySesId:
    async def test_find_message(self, db: AsyncSession):
        ses_id = f"find-{uuid4().hex[:8]}"
        msg = await create_test_message(db, ses_message_id=ses_id)
        found = await get_message_by_ses_id(db, ses_id)
        assert found is not None
        assert found.id == msg.id

    async def test_strip_angle_brackets(self, db: AsyncSession):
        ses_id = f"brackets-{uuid4().hex[:8]}"
        msg = await create_test_message(db, ses_message_id=ses_id)
        found = await get_message_by_ses_id(db, f"<{ses_id}>")
        assert found is not None
        assert found.id == msg.id

    async def test_not_found(self, db: AsyncSession):
        found = await get_message_by_ses_id(db, "nonexistent-ses-id")
        assert found is None


class TestHandleDelivery:
    async def test_delivery_updates_status(self, db: AsyncSession, sample_delivery_event):
        ses_id = f"delivery-{uuid4().hex[:8]}"
        msg = await create_test_message(db, ses_message_id=ses_id)
        sample_delivery_event["mail"]["messageId"] = ses_id

        await handle_delivery(db, sample_delivery_event)
        await db.refresh(msg)

        assert msg.status == "delivered"

    async def test_delivery_creates_event(self, db: AsyncSession, sample_delivery_event):
        ses_id = f"del-evt-{uuid4().hex[:8]}"
        msg = await create_test_message(db, ses_message_id=ses_id)
        sample_delivery_event["mail"]["messageId"] = ses_id

        await handle_delivery(db, sample_delivery_event)

        events = (await db.execute(
            select(Event).where(Event.message_id == msg.id)
        )).scalars().all()
        assert len(events) == 1
        assert events[0].event_type == "delivery"

    async def test_delivery_from_deferred(self, db: AsyncSession, sample_delivery_event):
        ses_id = f"def-del-{uuid4().hex[:8]}"
        msg = await create_test_message(db, ses_message_id=ses_id, status="deferred")
        sample_delivery_event["mail"]["messageId"] = ses_id

        await handle_delivery(db, sample_delivery_event)
        await db.refresh(msg)

        assert msg.status == "delivered"

    async def test_delivery_ignores_bounced(self, db: AsyncSession, sample_delivery_event):
        ses_id = f"bounced-del-{uuid4().hex[:8]}"
        msg = await create_test_message(db, ses_message_id=ses_id, status="bounced")
        sample_delivery_event["mail"]["messageId"] = ses_id

        await handle_delivery(db, sample_delivery_event)
        await db.refresh(msg)

        assert msg.status == "bounced"  # Status unchanged

    async def test_delivery_missing_message(self, db: AsyncSession, sample_delivery_event):
        sample_delivery_event["mail"]["messageId"] = "nonexistent"
        # Should not raise
        await handle_delivery(db, sample_delivery_event)


class TestHandleBounce:
    async def test_hard_bounce(self, db: AsyncSession, sample_bounce_event):
        ses_id = f"bounce-{uuid4().hex[:8]}"
        email = f"bounce-{uuid4().hex[:8]}@example.com"
        msg = await create_test_message(db, ses_message_id=ses_id, to_email=email)
        sample_bounce_event["mail"]["messageId"] = ses_id

        await handle_bounce(db, sample_bounce_event)
        await db.refresh(msg)

        assert msg.status == "bounced"

        # Check suppression was created
        sup = (await db.execute(
            select(Suppression).where(Suppression.email == email)
        )).scalar_one_or_none()
        assert sup is not None
        assert sup.reason == "hard_bounce"

    async def test_soft_bounce_no_suppression(self, db: AsyncSession, sample_bounce_event):
        ses_id = f"soft-{uuid4().hex[:8]}"
        email = f"soft-{uuid4().hex[:8]}@example.com"
        msg = await create_test_message(db, ses_message_id=ses_id, to_email=email)
        sample_bounce_event["mail"]["messageId"] = ses_id
        sample_bounce_event["bounce"]["bounceType"] = "Transient"

        await handle_bounce(db, sample_bounce_event)
        await db.refresh(msg)

        assert msg.status == "bounced"

        # No suppression for soft bounce
        sup = (await db.execute(
            select(Suppression).where(Suppression.email == email)
        )).scalar_one_or_none()
        assert sup is None

    async def test_bounce_creates_event(self, db: AsyncSession, sample_bounce_event):
        ses_id = f"bev-{uuid4().hex[:8]}"
        msg = await create_test_message(db, ses_message_id=ses_id)
        sample_bounce_event["mail"]["messageId"] = ses_id

        await handle_bounce(db, sample_bounce_event)

        events = (await db.execute(
            select(Event).where(Event.message_id == msg.id)
        )).scalars().all()
        assert len(events) == 1
        assert events[0].event_type == "bounce"
        assert events[0].bounce_type == "hard"


class TestHandleComplaint:
    async def test_complaint_updates_status(self, db: AsyncSession, sample_complaint_event):
        ses_id = f"complaint-{uuid4().hex[:8]}"
        email = f"complain-{uuid4().hex[:8]}@example.com"
        msg = await create_test_message(db, ses_message_id=ses_id, to_email=email)
        sample_complaint_event["mail"]["messageId"] = ses_id

        await handle_complaint(db, sample_complaint_event)
        await db.refresh(msg)

        assert msg.status == "complained"

        # Check auto-suppression
        sup = (await db.execute(
            select(Suppression).where(Suppression.email == email)
        )).scalar_one_or_none()
        assert sup is not None
        assert sup.reason == "complaint"


class TestHandleDeliveryDelay:
    async def test_delay_updates_status(self, db: AsyncSession, sample_delay_event):
        ses_id = f"delay-{uuid4().hex[:8]}"
        msg = await create_test_message(db, ses_message_id=ses_id)
        sample_delay_event["mail"]["messageId"] = ses_id

        await handle_delivery_delay(db, sample_delay_event)
        await db.refresh(msg)

        assert msg.status == "deferred"
        assert msg.first_deferred_at is not None

    async def test_delay_preserves_first_deferred_at(self, db: AsyncSession, sample_delay_event):
        ses_id = f"delay2-{uuid4().hex[:8]}"
        msg = await create_test_message(db, ses_message_id=ses_id)
        sample_delay_event["mail"]["messageId"] = ses_id

        await handle_delivery_delay(db, sample_delay_event)
        await db.refresh(msg)  # Refresh to get tz-aware datetime from DB
        first_deferred = msg.first_deferred_at

        # Second delay should not update first_deferred_at
        # (status is already deferred, so it won't update)
        await handle_delivery_delay(db, sample_delay_event)
        await db.refresh(msg)

        assert msg.first_deferred_at == first_deferred

    async def test_delay_creates_event(self, db: AsyncSession, sample_delay_event):
        ses_id = f"dev-{uuid4().hex[:8]}"
        msg = await create_test_message(db, ses_message_id=ses_id)
        sample_delay_event["mail"]["messageId"] = ses_id

        await handle_delivery_delay(db, sample_delay_event)

        events = (await db.execute(
            select(Event).where(Event.message_id == msg.id)
        )).scalars().all()
        assert len(events) == 1
        assert events[0].event_type == "delay"
        assert events[0].delay_type == "MailboxFull"


class TestHandleReject:
    async def test_reject_updates_status(self, db: AsyncSession, sample_reject_event):
        ses_id = f"reject-{uuid4().hex[:8]}"
        msg = await create_test_message(db, ses_message_id=ses_id)
        sample_reject_event["mail"]["messageId"] = ses_id

        await handle_reject(db, sample_reject_event)
        await db.refresh(msg)

        assert msg.status == "rejected"


class TestProcessSesEvent:
    async def test_routes_delivery(self, db: AsyncSession, sample_delivery_event):
        ses_id = f"route-del-{uuid4().hex[:8]}"
        msg = await create_test_message(db, ses_message_id=ses_id)
        sample_delivery_event["mail"]["messageId"] = ses_id

        await process_ses_event(db, sample_delivery_event)
        await db.refresh(msg)

        assert msg.status == "delivered"

    async def test_unknown_event_type(self, db: AsyncSession):
        event = {"eventType": "UnknownType", "mail": {"messageId": "test"}}
        # Should not raise
        await process_ses_event(db, event)

    async def test_missing_event_type(self, db: AsyncSession):
        event = {"mail": {"messageId": "test"}}
        # Should not raise
        await process_ses_event(db, event)


class TestAddToSuppressionList:
    async def test_add_new(self, db: AsyncSession):
        email = f"auto-sup-{uuid4().hex[:8]}@example.com"
        await add_to_suppression_list(db, email, "hard_bounce")
        await db.flush()  # Flush so the select below can find it

        sup = (await db.execute(
            select(Suppression).where(Suppression.email == email)
        )).scalar_one_or_none()
        assert sup is not None

    async def test_idempotent(self, db: AsyncSession):
        email = f"idem-{uuid4().hex[:8]}@example.com"
        await add_to_suppression_list(db, email, "hard_bounce")
        await db.flush()
        # Second call should not raise
        await add_to_suppression_list(db, email, "complaint")
