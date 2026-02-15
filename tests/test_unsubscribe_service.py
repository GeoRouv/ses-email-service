"""Tests for unsubscribe service."""

from datetime import datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.suppression import Suppression
from app.services.unsubscribe_service import (
    build_unsubscribe_url,
    generate_unsubscribe_token,
    process_unsubscribe,
    validate_unsubscribe_token,
)


class TestGenerateToken:
    def test_generates_valid_jwt(self):
        token = generate_unsubscribe_token("user@example.com", "msg-123")
        assert isinstance(token, str)
        assert len(token) > 0

    def test_token_contains_email(self):
        token = generate_unsubscribe_token("user@example.com", "msg-123")
        payload = jwt.decode(token, settings.UNSUBSCRIBE_SECRET, algorithms=["HS256"])
        assert payload["email"] == "user@example.com"
        assert payload["message_id"] == "msg-123"

    def test_token_has_expiry(self):
        token = generate_unsubscribe_token("user@example.com", "msg-123")
        payload = jwt.decode(token, settings.UNSUBSCRIBE_SECRET, algorithms=["HS256"])
        assert "exp" in payload
        assert "iat" in payload


class TestValidateToken:
    def test_valid_token(self):
        token = generate_unsubscribe_token("user@example.com", "msg-123")
        payload = validate_unsubscribe_token(token)
        assert payload is not None
        assert payload["email"] == "user@example.com"

    def test_expired_token(self):
        payload = {
            "email": "user@example.com",
            "message_id": "msg-123",
            "iat": datetime.utcnow() - timedelta(days=31),
            "exp": datetime.utcnow() - timedelta(days=1),
        }
        token = jwt.encode(payload, settings.UNSUBSCRIBE_SECRET, algorithm="HS256")
        result = validate_unsubscribe_token(token)
        assert result is None

    def test_invalid_token(self):
        result = validate_unsubscribe_token("invalid-garbage-token")
        assert result is None

    def test_wrong_secret(self):
        payload = {
            "email": "user@example.com",
            "message_id": "msg-123",
            "exp": datetime.utcnow() + timedelta(days=30),
        }
        token = jwt.encode(payload, "wrong-secret", algorithm="HS256")
        result = validate_unsubscribe_token(token)
        assert result is None


class TestBuildUnsubscribeUrl:
    def test_builds_url(self):
        url = build_unsubscribe_url("user@example.com", "msg-123")
        assert url.startswith(settings.APP_BASE_URL)
        assert "/unsubscribe/" in url

    def test_url_contains_valid_token(self):
        url = build_unsubscribe_url("user@example.com", "msg-123")
        token = url.split("/unsubscribe/")[1]
        payload = validate_unsubscribe_token(token)
        assert payload is not None
        assert payload["email"] == "user@example.com"


class TestProcessUnsubscribe:
    async def test_new_unsubscribe(self, db: AsyncSession):
        email = f"unsub-{uuid4().hex[:8]}@example.com"
        result = await process_unsubscribe(db, email)
        assert result is True

        # Verify in database
        stmt = select(Suppression).where(Suppression.email == email.lower())
        sup = (await db.execute(stmt)).scalar_one_or_none()
        assert sup is not None
        assert sup.reason == "unsubscribe"

    async def test_idempotent_unsubscribe(self, db: AsyncSession):
        email = f"idempotent-{uuid4().hex[:8]}@example.com"

        # First unsubscribe
        result1 = await process_unsubscribe(db, email)
        assert result1 is True

        # Second unsubscribe — should succeed (idempotent)
        result2 = await process_unsubscribe(db, email)
        assert result2 is True
