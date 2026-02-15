"""Integration test: full email send flow with webhook processing."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.models.message import Message
from app.schemas.email import SendEmailRequest
from app.services.email_service import send_email
from app.services.webhook_service import process_ses_event


class TestFullSendFlow:
    """End-to-end: send email → verify DB → simulate webhook → verify status."""

    @patch("app.services.email_service.ses_client")
    async def test_send_then_deliver(self, mock_ses, db: AsyncSession):
        """Send email, then simulate SES delivery webhook."""
        ses_id = f"integ-{uuid4().hex[:8]}"
        mock_ses.send_email = AsyncMock(return_value=ses_id)

        # Step 1: Send email
        request = SendEmailRequest(
            to_email="recipient@example.com",
            from_email="sender@test.example.com",
            subject="Integration Test",
            html_content="<p>Hello integration</p>",
        )
        response = await send_email(db, request)

        assert response.success is True
        assert response.status == "sent"

        # Step 2: Verify message in DB
        msg = (await db.execute(
            select(Message).where(Message.id == response.message_id)
        )).scalar_one()
        assert msg.ses_message_id == ses_id
        assert msg.status == "sent"

        # Step 3: Simulate delivery webhook
        delivery_event = {
            "eventType": "Delivery",
            "mail": {
                "messageId": ses_id,
                "timestamp": "2024-01-15T10:30:00.000Z",
                "source": "sender@test.example.com",
                "destination": ["recipient@example.com"],
            },
            "delivery": {
                "timestamp": "2024-01-15T10:30:01.000Z",
                "recipients": ["recipient@example.com"],
                "processingTimeMillis": 500,
            },
        }
        await process_ses_event(db, delivery_event)

        # Step 4: Verify status updated
        await db.refresh(msg)
        assert msg.status == "delivered"

        # Step 5: Verify event recorded
        events = (await db.execute(
            select(Event).where(Event.message_id == msg.id)
        )).scalars().all()
        assert len(events) == 1
        assert events[0].event_type == "delivery"

    @patch("app.services.email_service.ses_client")
    async def test_send_then_bounce(self, mock_ses, db: AsyncSession):
        """Send email, then simulate SES hard bounce webhook."""
        ses_id = f"integ-bounce-{uuid4().hex[:8]}"
        mock_ses.send_email = AsyncMock(return_value=ses_id)

        request = SendEmailRequest(
            to_email="recipient@example.com",
            from_email="sender@test.example.com",
            subject="Bounce Integration Test",
            html_content="<p>This will bounce</p>",
        )
        response = await send_email(db, request)
        assert response.success is True

        # Simulate bounce
        bounce_event = {
            "eventType": "Bounce",
            "mail": {
                "messageId": ses_id,
                "timestamp": "2024-01-15T10:30:00.000Z",
                "source": "sender@test.example.com",
                "destination": ["recipient@example.com"],
            },
            "bounce": {
                "bounceType": "Permanent",
                "timestamp": "2024-01-15T10:30:01.000Z",
                "bouncedRecipients": [
                    {"emailAddress": "recipient@example.com", "diagnosticCode": "550"}
                ],
            },
        }
        await process_ses_event(db, bounce_event)

        msg = (await db.execute(
            select(Message).where(Message.id == response.message_id)
        )).scalar_one()
        assert msg.status == "bounced"

    @patch("app.services.email_service.ses_client")
    async def test_send_then_delay_then_deliver(self, mock_ses, db: AsyncSession):
        """Send email, simulate delay, then delivery."""
        ses_id = f"integ-delay-{uuid4().hex[:8]}"
        mock_ses.send_email = AsyncMock(return_value=ses_id)

        request = SendEmailRequest(
            to_email="recipient@example.com",
            from_email="sender@test.example.com",
            subject="Delay then Deliver",
            html_content="<p>Delayed delivery</p>",
        )
        response = await send_email(db, request)

        # Simulate delay
        delay_event = {
            "eventType": "DeliveryDelay",
            "mail": {
                "messageId": ses_id,
                "timestamp": "2024-01-15T10:30:00.000Z",
                "source": "sender@test.example.com",
                "destination": ["recipient@example.com"],
            },
            "deliveryDelay": {
                "timestamp": "2024-01-15T10:35:00.000Z",
                "delayType": "MailboxFull",
                "delayedRecipients": [
                    {"emailAddress": "recipient@example.com", "diagnosticCode": "452"}
                ],
            },
        }
        await process_ses_event(db, delay_event)

        msg = (await db.execute(
            select(Message).where(Message.id == response.message_id)
        )).scalar_one()
        assert msg.status == "deferred"
        assert msg.first_deferred_at is not None

        # Then delivery
        delivery_event = {
            "eventType": "Delivery",
            "mail": {
                "messageId": ses_id,
                "timestamp": "2024-01-15T10:40:00.000Z",
                "source": "sender@test.example.com",
                "destination": ["recipient@example.com"],
            },
            "delivery": {
                "timestamp": "2024-01-15T10:40:01.000Z",
                "recipients": ["recipient@example.com"],
                "processingTimeMillis": 500,
            },
        }
        await process_ses_event(db, delivery_event)

        await db.refresh(msg)
        assert msg.status == "delivered"

        # Should have 2 events total: delay + delivery
        events = (await db.execute(
            select(Event).where(Event.message_id == msg.id)
        )).scalars().all()
        assert len(events) == 2
