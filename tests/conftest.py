"""Test fixtures for the SES Email Service test suite."""

import os
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Set test environment variables BEFORE importing app modules
os.environ.update({
    "DATABASE_URL": "postgresql+asyncpg://postgres:postgres@localhost:5432/ses_email_test",
    "AWS_ACCESS_KEY_ID": "test-key-id",
    "AWS_SECRET_ACCESS_KEY": "test-secret-key",
    "AWS_REGION": "us-east-1",
    "SES_CONFIGURATION_SET": "test-config-set",
    "SNS_TOPIC_ARN": "arn:aws:sns:us-east-1:123456789:test-topic",
    "VERIFIED_DOMAIN": "test.example.com",
    "APP_BASE_URL": "http://localhost:8000",
    "UNSUBSCRIBE_SECRET": "test-secret-key-for-jwt-minimum-32bytes!",
    "FALLBACK_REDIRECT_URL": "https://example.com",
    "ALLOWED_EMAIL_DOMAINS": "example.com,test.example.com",
    "ENVIRONMENT": "test",
    "LOG_LEVEL": "WARNING",
})

from app.database import Base  # noqa: E402
from app.main import create_app  # noqa: E402
from app.database import get_session  # noqa: E402

TEST_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/ses_email_test"

# Track whether tables have been set up this session
_tables_created = False


@pytest.fixture(autouse=True)
async def _ensure_tables():
    """Create tables once per session, on the current event loop."""
    global _tables_created
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    if not _tables_created:
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        _tables_created = True
    await engine.dispose()


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    """Provide a transactional database session that rolls back after each test."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def committed_db() -> AsyncGenerator[AsyncSession, None]:
    """Provide a database session that commits (for integration tests)."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    async with factory() as session:
        yield session
        await session.commit()
    await engine.dispose()


@pytest.fixture
def mock_ses_client():
    """Mock the SES client to avoid real AWS calls."""
    mock = AsyncMock()
    mock.send_email.return_value = "test-ses-message-id-123"
    mock.verify_domain.return_value = "test-verification-token"
    mock.verify_domain_dkim.return_value = ["token1", "token2", "token3"]
    mock.get_domain_verification_status.return_value = {"VerificationStatus": "Success"}
    mock.get_domain_dkim_status.return_value = {"DkimVerified": True}
    return mock


@pytest.fixture
async def client(db: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Create a test HTTP client with database session override."""
    app = create_app()

    async def override_get_session():
        yield db

    app.dependency_overrides[get_session] = override_get_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
def sample_message_data():
    """Sample message data for tests."""
    return {
        "to_email": "recipient@example.com",
        "from_email": "sender@test.example.com",
        "from_name": "Test Sender",
        "subject": "Test Email Subject",
        "html_content": "<html><body><h1>Hello</h1><a href='https://example.com'>Link</a></body></html>",
        "text_content": "Hello plain text",
    }


@pytest.fixture
def sample_delivery_event():
    """Sample SES Delivery event payload."""
    return {
        "eventType": "Delivery",
        "mail": {
            "messageId": "test-ses-message-id-123",
            "timestamp": "2024-01-15T10:30:00.000Z",
            "source": "sender@test.example.com",
            "destination": ["recipient@example.com"],
        },
        "delivery": {
            "timestamp": "2024-01-15T10:30:01.000Z",
            "recipients": ["recipient@example.com"],
            "processingTimeMillis": 1000,
        },
    }


@pytest.fixture
def sample_bounce_event():
    """Sample SES Bounce event payload."""
    return {
        "eventType": "Bounce",
        "mail": {
            "messageId": "test-ses-message-id-123",
            "timestamp": "2024-01-15T10:30:00.000Z",
            "source": "sender@test.example.com",
            "destination": ["bounce@example.com"],
        },
        "bounce": {
            "bounceType": "Permanent",
            "timestamp": "2024-01-15T10:30:01.000Z",
            "bouncedRecipients": [
                {
                    "emailAddress": "bounce@example.com",
                    "diagnosticCode": "smtp; 550 User not found",
                }
            ],
        },
    }


@pytest.fixture
def sample_complaint_event():
    """Sample SES Complaint event payload."""
    return {
        "eventType": "Complaint",
        "mail": {
            "messageId": "test-ses-message-id-123",
            "timestamp": "2024-01-15T10:30:00.000Z",
            "source": "sender@test.example.com",
            "destination": ["complainer@example.com"],
        },
        "complaint": {
            "timestamp": "2024-01-15T10:31:00.000Z",
            "complainedRecipients": [
                {"emailAddress": "complainer@example.com"}
            ],
            "complaintFeedbackType": "abuse",
        },
    }


@pytest.fixture
def sample_delay_event():
    """Sample SES DeliveryDelay event payload."""
    return {
        "eventType": "DeliveryDelay",
        "mail": {
            "messageId": "test-ses-message-id-123",
            "timestamp": "2024-01-15T10:30:00.000Z",
            "source": "sender@test.example.com",
            "destination": ["slow@example.com"],
        },
        "deliveryDelay": {
            "timestamp": "2024-01-15T10:35:00.000Z",
            "delayType": "MailboxFull",
            "delayedRecipients": [
                {
                    "emailAddress": "slow@example.com",
                    "diagnosticCode": "smtp; 452 Mailbox full",
                }
            ],
        },
    }


@pytest.fixture
def sample_reject_event():
    """Sample SES Reject event payload."""
    return {
        "eventType": "Reject",
        "mail": {
            "messageId": "test-ses-message-id-123",
            "timestamp": "2024-01-15T10:30:00.000Z",
            "source": "sender@test.example.com",
            "destination": ["rejected@example.com"],
        },
        "reject": {
            "timestamp": "2024-01-15T10:30:00.500Z",
            "reason": "Bad content",
        },
    }
