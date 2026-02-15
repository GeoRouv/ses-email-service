"""Tests for tracking service (opens and clicks)."""

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.click_event import ClickEvent
from app.models.message import Message
from app.services.tracking_service import (
    get_click_count,
    get_message_by_id,
    get_unique_click_count,
    record_click,
    record_open,
)


async def create_test_message(db: AsyncSession, **kwargs) -> Message:
    """Helper to create a test message."""
    defaults = {
        "id": uuid4(),
        "ses_message_id": f"ses-{uuid4().hex[:8]}",
        "to_email": "recipient@example.com",
        "from_email": "sender@test.example.com",
        "subject": "Test Subject",
        "html_content": "<p>Test</p>",
        "status": "sent",
    }
    defaults.update(kwargs)
    msg = Message(**defaults)
    db.add(msg)
    await db.flush()
    return msg


class TestGetMessageById:
    async def test_find_by_uuid(self, db: AsyncSession):
        msg = await create_test_message(db)
        found = await get_message_by_id(db, msg.id)
        assert found is not None
        assert found.id == msg.id

    async def test_find_by_string(self, db: AsyncSession):
        msg = await create_test_message(db)
        found = await get_message_by_id(db, str(msg.id))
        assert found is not None
        assert found.id == msg.id

    async def test_invalid_string(self, db: AsyncSession):
        found = await get_message_by_id(db, "not-a-uuid")
        assert found is None

    async def test_not_found(self, db: AsyncSession):
        found = await get_message_by_id(db, uuid4())
        assert found is None


class TestRecordOpen:
    async def test_first_open(self, db: AsyncSession):
        msg = await create_test_message(db)
        result = await record_open(db, str(msg.id))

        assert result is True
        await db.refresh(msg)
        assert msg.opened_at is not None

    async def test_second_open_ignored(self, db: AsyncSession):
        msg = await create_test_message(db)

        # First open
        await record_open(db, str(msg.id))
        await db.refresh(msg)
        first_opened = msg.opened_at

        # Second open — should be ignored
        result = await record_open(db, str(msg.id))
        assert result is False
        await db.refresh(msg)
        assert msg.opened_at == first_opened

    async def test_open_nonexistent_message(self, db: AsyncSession):
        result = await record_open(db, str(uuid4()))
        assert result is False


class TestRecordClick:
    async def test_record_click(self, db: AsyncSession):
        msg = await create_test_message(db)
        result = await record_click(db, str(msg.id), "https://example.com")

        assert result is True

        clicks = (await db.execute(
            select(ClickEvent).where(ClickEvent.message_id == msg.id)
        )).scalars().all()
        assert len(clicks) == 1
        assert clicks[0].url == "https://example.com"

    async def test_multiple_clicks_recorded(self, db: AsyncSession):
        msg = await create_test_message(db)

        await record_click(db, str(msg.id), "https://a.com")
        await record_click(db, str(msg.id), "https://b.com")
        await record_click(db, str(msg.id), "https://a.com")  # Duplicate URL

        clicks = (await db.execute(
            select(ClickEvent).where(ClickEvent.message_id == msg.id)
        )).scalars().all()
        assert len(clicks) == 3

    async def test_click_nonexistent_message(self, db: AsyncSession):
        result = await record_click(db, str(uuid4()), "https://example.com")
        assert result is False


class TestGetClickCount:
    async def test_count_clicks(self, db: AsyncSession):
        msg = await create_test_message(db)

        await record_click(db, str(msg.id), "https://a.com")
        await record_click(db, str(msg.id), "https://b.com")

        count = await get_click_count(db, msg.id)
        assert count == 2

    async def test_zero_clicks(self, db: AsyncSession):
        msg = await create_test_message(db)
        count = await get_click_count(db, msg.id)
        assert count == 0


class TestGetUniqueClickCount:
    async def test_unique_clicks(self, db: AsyncSession):
        msg = await create_test_message(db)

        await record_click(db, str(msg.id), "https://a.com")
        await record_click(db, str(msg.id), "https://b.com")
        await record_click(db, str(msg.id), "https://a.com")  # Duplicate

        unique = await get_unique_click_count(db, msg.id)
        assert unique == 2
