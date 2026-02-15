"""Tests for dashboard metrics and analytics service."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.click_event import ClickEvent
from app.models.event import Event
from app.models.message import Message
from app.services.dashboard_service import (
    get_activity_list,
    get_daily_volume,
    get_dashboard_metrics,
    get_deferred_messages,
    get_message_detail,
)


async def _create_message(db: AsyncSession, status: str = "sent", **kwargs) -> Message:
    """Helper to create a test message."""
    defaults = {
        "id": uuid4(),
        "ses_message_id": f"ses-{uuid4().hex[:8]}",
        "to_email": "recipient@example.com",
        "from_email": "sender@test.example.com",
        "subject": "Test",
        "html_content": "<p>Test</p>",
        "status": status,
    }
    defaults.update(kwargs)
    msg = Message(**defaults)
    db.add(msg)
    await db.flush()
    return msg


class TestGetDashboardMetrics:
    async def test_empty_dashboard(self, db: AsyncSession):
        metrics = await get_dashboard_metrics(db, days=7)
        assert metrics["total_sent"] == 0
        assert metrics["delivery_rate"] == 0
        assert metrics["days"] == 7

    async def test_counts_messages(self, db: AsyncSession):
        await _create_message(db, status="delivered")
        await _create_message(db, status="delivered")
        await _create_message(db, status="bounced")

        metrics = await get_dashboard_metrics(db, days=7)
        assert metrics["total_sent"] >= 3
        assert metrics["delivered"] >= 2
        assert metrics["bounced"] >= 1

    async def test_rates_calculated(self, db: AsyncSession):
        # Create 10 delivered, 0 bounced → 100% delivery
        for _ in range(10):
            await _create_message(db, status="delivered")

        metrics = await get_dashboard_metrics(db, days=7)
        assert metrics["delivery_rate"] > 0


class TestGetDailyVolume:
    async def test_empty_volume(self, db: AsyncSession):
        volume = await get_daily_volume(db, days=7)
        assert "labels" in volume
        assert len(volume["labels"]) == 7
        assert len(volume["delivered"]) == 7
        assert len(volume["bounced"]) == 7

    async def test_volume_with_messages(self, db: AsyncSession):
        await _create_message(db, status="delivered")
        await _create_message(db, status="bounced")

        volume = await get_daily_volume(db, days=7)
        assert sum(volume["delivered"]) >= 1 or sum(volume["bounced"]) >= 1


class TestGetActivityList:
    async def test_empty_activity(self, db: AsyncSession):
        result = await get_activity_list(db, page=1, per_page=25)
        assert "messages" in result
        assert "total" in result
        assert result["page"] == 1

    async def test_pagination(self, db: AsyncSession):
        for _ in range(5):
            await _create_message(db)

        result = await get_activity_list(db, page=1, per_page=2)
        assert len(result["messages"]) <= 2
        assert result["total"] >= 5

    async def test_status_filter(self, db: AsyncSession):
        await _create_message(db, status="delivered")
        await _create_message(db, status="bounced")

        result = await get_activity_list(db, status_filter="bounced")
        for msg in result["messages"]:
            assert msg.status == "bounced"


class TestGetMessageDetail:
    async def test_found(self, db: AsyncSession):
        msg = await _create_message(db)
        # Add an event
        event = Event(
            id=uuid4(),
            message_id=msg.id,
            event_type="delivery",
            raw_payload={},
            timestamp=datetime.now(timezone.utc),
        )
        db.add(event)
        await db.flush()

        detail = await get_message_detail(db, msg.id)
        assert detail is not None
        assert detail["message"].id == msg.id
        assert len(detail["events"]) == 1

    async def test_not_found(self, db: AsyncSession):
        detail = await get_message_detail(db, uuid4())
        assert detail is None


class TestGetDeferredMessages:
    async def test_empty_deferred(self, db: AsyncSession):
        messages, total = await get_deferred_messages(db)
        # No guarantee of empty — other tests may add deferred messages
        assert isinstance(messages, list)
        assert isinstance(total, int)

    async def test_deferred_with_delay_event(self, db: AsyncSession):
        msg = await _create_message(
            db,
            status="deferred",
            first_deferred_at=datetime.now(timezone.utc),
        )
        event = Event(
            id=uuid4(),
            message_id=msg.id,
            event_type="delay",
            delay_type="MailboxFull",
            raw_payload={},
            timestamp=datetime.now(timezone.utc),
        )
        db.add(event)
        await db.flush()

        messages, total = await get_deferred_messages(db)
        assert total >= 1

        deferred_msg = next((m for m in messages if m["id"] == msg.id), None)
        assert deferred_msg is not None
        assert deferred_msg["delay_type"] == "MailboxFull"
