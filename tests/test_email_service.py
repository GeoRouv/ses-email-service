"""Tests for email sending service."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import Message
from app.models.suppression import Suppression
from app.schemas.email import SendEmailRequest
from app.services.email_service import check_suppression, send_email
from app.services.ses_client import SESError


async def _add_suppression(db: AsyncSession, email: str) -> None:
    """Helper to add a suppressed email."""
    sup = Suppression(id=uuid4(), email=email.lower(), reason="hard_bounce")
    db.add(sup)
    await db.flush()


class TestCheckSuppression:
    async def test_suppressed_email(self, db: AsyncSession):
        email = f"sup-{uuid4().hex[:8]}@example.com"
        await _add_suppression(db, email)
        assert await check_suppression(db, email) is True

    async def test_not_suppressed(self, db: AsyncSession):
        assert await check_suppression(db, f"clean-{uuid4().hex[:8]}@example.com") is False

    async def test_case_insensitive(self, db: AsyncSession):
        email = f"case-{uuid4().hex[:8]}@example.com"
        await _add_suppression(db, email)
        assert await check_suppression(db, email.upper()) is True


class TestSendEmail:
    """Tests for the send_email service function."""

    def _make_request(self, **overrides) -> SendEmailRequest:
        defaults = {
            "to_email": "recipient@example.com",
            "from_email": "sender@test.example.com",
            "subject": "Test Subject",
            "html_content": "<p>Hello</p>",
        }
        defaults.update(overrides)
        return SendEmailRequest(**defaults)

    @patch("app.services.email_service.ses_client")
    async def test_successful_send(self, mock_ses, db: AsyncSession):
        mock_ses.send_email = AsyncMock(return_value="ses-msg-id-abc")
        request = self._make_request()

        response = await send_email(db, request)

        assert response.success is True
        assert response.ses_message_id == "ses-msg-id-abc"
        assert response.status == "sent"
        assert response.message_id is not None

    @patch("app.services.email_service.ses_client")
    async def test_strips_angle_brackets_from_ses_id(self, mock_ses, db: AsyncSession):
        mock_ses.send_email = AsyncMock(return_value="<ses-msg-id-abc>")
        request = self._make_request()

        response = await send_email(db, request)
        assert response.ses_message_id == "ses-msg-id-abc"

    @patch("app.services.email_service.ses_client")
    async def test_message_saved_to_db(self, mock_ses, db: AsyncSession):
        mock_ses.send_email = AsyncMock(return_value="ses-db-test")
        request = self._make_request()

        response = await send_email(db, request)

        msg = (await db.execute(
            select(Message).where(Message.id == response.message_id)
        )).scalar_one_or_none()
        assert msg is not None
        assert msg.to_email == "recipient@example.com"
        assert msg.status == "sent"

    @patch("app.services.email_service.ses_client")
    async def test_with_from_name(self, mock_ses, db: AsyncSession):
        mock_ses.send_email = AsyncMock(return_value="ses-name-test")
        request = self._make_request(from_name="Test Sender")

        response = await send_email(db, request)
        assert response.success is True

        # Verify ses_client.send_email was called with "Name <email>" source
        call_kwargs = mock_ses.send_email.call_args.kwargs
        assert "Test Sender" in call_kwargs["source"]

    async def test_invalid_recipient_email(self, db: AsyncSession):
        # Email has @ (passes Pydantic) but consecutive dots (fails validate_email)
        request = self._make_request(to_email="user..bad@example.com")
        with pytest.raises(HTTPException) as exc_info:
            await send_email(db, request)
        assert exc_info.value.status_code == 400

    async def test_invalid_sender_email(self, db: AsyncSession):
        # Email has @ (passes Pydantic) but consecutive dots (fails validate_email)
        request = self._make_request(from_email="bad..sender@example.com")
        with pytest.raises(HTTPException) as exc_info:
            await send_email(db, request)
        assert exc_info.value.status_code == 400

    @patch("app.services.email_service.ses_client")
    async def test_suppressed_recipient_rejected(self, mock_ses, db: AsyncSession):
        email = f"suppressed-{uuid4().hex[:8]}@example.com"
        await _add_suppression(db, email)

        request = self._make_request(to_email=email)
        with pytest.raises(HTTPException) as exc_info:
            await send_email(db, request)
        assert exc_info.value.status_code == 400
        assert "suppressed" in str(exc_info.value.detail).lower()

    @patch("app.services.email_service.ses_client")
    async def test_unverified_sender_domain_rejected(self, mock_ses, db: AsyncSession):
        # Use a sender domain that's neither VERIFIED_DOMAIN nor in the DB
        request = self._make_request(from_email="sender@unverified-domain.com")
        with pytest.raises(HTTPException) as exc_info:
            await send_email(db, request)
        assert exc_info.value.status_code == 403
        assert "not verified" in str(exc_info.value.detail).lower()

    @patch("app.services.email_service.ses_client")
    async def test_ses_error_raises_500(self, mock_ses, db: AsyncSession):
        mock_ses.send_email = AsyncMock(side_effect=SESError("SES is down"))
        request = self._make_request()

        with pytest.raises(HTTPException) as exc_info:
            await send_email(db, request)
        assert exc_info.value.status_code == 500

    @patch("app.services.email_service.ses_client")
    async def test_unexpected_error_raises_500(self, mock_ses, db: AsyncSession):
        mock_ses.send_email = AsyncMock(side_effect=RuntimeError("Something broke"))
        request = self._make_request()

        with pytest.raises(HTTPException) as exc_info:
            await send_email(db, request)
        assert exc_info.value.status_code == 500

    @patch("app.services.email_service.ses_client")
    async def test_html_is_processed_with_tracking(self, mock_ses, db: AsyncSession):
        mock_ses.send_email = AsyncMock(return_value="ses-tracking-test")
        request = self._make_request(
            html_content='<html><body><a href="https://example.com">Link</a></body></html>'
        )

        response = await send_email(db, request)

        # Verify the HTML sent to SES includes tracking rewrites
        call_kwargs = mock_ses.send_email.call_args.kwargs
        sent_html = call_kwargs["html"]
        # Should have tracking pixel
        assert "track/open" in sent_html or "pixel" in sent_html.lower() or "img" in sent_html.lower()

    @patch("app.services.email_service.ses_client")
    async def test_domain_not_allowed(self, mock_ses, db: AsyncSession):
        # Settings have ALLOWED_EMAIL_DOMAINS="example.com,test.example.com"
        request = self._make_request(to_email="user@notallowed.com")
        with pytest.raises(HTTPException) as exc_info:
            await send_email(db, request)
        assert exc_info.value.status_code == 403
