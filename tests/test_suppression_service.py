"""Tests for suppression list management service."""

from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.suppression import Suppression
from app.schemas.suppression import AddSuppressionRequest
from app.services.suppression_service import (
    add_suppression,
    check_suppression,
    get_suppressions,
    remove_suppression,
)


class TestGetSuppressions:
    async def test_empty_list(self, db: AsyncSession):
        # Use a filter that won't match anything
        suppressions, total = await get_suppressions(db, reason="nonexistent_reason")
        assert total == 0
        assert len(suppressions) == 0

    async def test_pagination(self, db: AsyncSession):
        # Add 3 suppressions
        for i in range(3):
            sup = Suppression(
                id=uuid4(),
                email=f"page-{uuid4().hex[:8]}@example.com",
                reason="manual",
            )
            db.add(sup)
        await db.flush()

        # Get page 1 with page_size=2
        suppressions, total = await get_suppressions(db, page=1, page_size=2)
        assert len(suppressions) <= 2
        assert total >= 3

    async def test_reason_filter(self, db: AsyncSession):
        unique = uuid4().hex[:8]
        sup = Suppression(
            id=uuid4(),
            email=f"filter-{unique}@example.com",
            reason=f"test_reason_{unique}",
        )
        db.add(sup)
        await db.flush()

        suppressions, total = await get_suppressions(db, reason=f"test_reason_{unique}")
        assert total == 1
        assert suppressions[0].email == f"filter-{unique}@example.com"


class TestAddSuppression:
    async def test_add_valid_suppression(self, db: AsyncSession):
        email = f"add-{uuid4().hex[:8]}@example.com"
        request = AddSuppressionRequest(email=email, reason="manual")
        suppression = await add_suppression(db, request)

        assert suppression.email == email.lower()
        assert suppression.reason == "manual"

    async def test_add_invalid_email(self, db: AsyncSession):
        # Email has @ (passes Pydantic) but consecutive dots (fails validate_email)
        request = AddSuppressionRequest(email="bad..dots@example.com", reason="manual")
        with pytest.raises(HTTPException) as exc_info:
            await add_suppression(db, request)
        assert exc_info.value.status_code == 400

    async def test_add_duplicate_suppression(self, db: AsyncSession):
        email = f"dup-{uuid4().hex[:8]}@example.com"
        request = AddSuppressionRequest(email=email, reason="manual")

        # First add
        await add_suppression(db, request)

        # Second add — should raise 409
        with pytest.raises(HTTPException) as exc_info:
            await add_suppression(db, request)
        assert exc_info.value.status_code == 409


class TestRemoveSuppression:
    async def test_remove_existing(self, db: AsyncSession):
        email = f"remove-{uuid4().hex[:8]}@example.com"
        sup = Suppression(id=uuid4(), email=email, reason="manual")
        db.add(sup)
        await db.flush()

        result = await remove_suppression(db, email)
        assert result is True

        # Verify removed
        stmt = select(Suppression).where(Suppression.email == email)
        check = (await db.execute(stmt)).scalar_one_or_none()
        assert check is None

    async def test_remove_nonexistent(self, db: AsyncSession):
        result = await remove_suppression(db, "nonexistent@example.com")
        assert result is False


class TestCheckSuppression:
    async def test_check_suppressed(self, db: AsyncSession):
        email = f"check-{uuid4().hex[:8]}@example.com"
        sup = Suppression(id=uuid4(), email=email, reason="hard_bounce")
        db.add(sup)
        await db.flush()

        result = await check_suppression(db, email)
        assert result.suppressed is True
        assert result.reason == "hard_bounce"

    async def test_check_not_suppressed(self, db: AsyncSession):
        result = await check_suppression(db, f"clean-{uuid4().hex[:8]}@example.com")
        assert result.suppressed is False
        assert result.reason is None
