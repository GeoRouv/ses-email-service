"""Email sending API routes."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.schemas.email import SendEmailRequest, SendEmailResponse
from app.services import email_service

router = APIRouter()


@router.post("/emails/send", response_model=SendEmailResponse)
async def send_email(
    request: SendEmailRequest,
    db: AsyncSession = Depends(get_session),
) -> SendEmailResponse:
    """
    Send an email via AWS SES.

    This endpoint:
    - Validates email addresses and checks domain allowlist
    - Checks if recipient is on suppression list
    - Sends email via AWS SES with retry logic
    - Stores message record in database
    - Returns message ID for tracking

    **Error Codes:**
    - `INVALID_RECIPIENT_EMAIL`: Recipient email format is invalid
    - `INVALID_SENDER_EMAIL`: Sender email format is invalid
    - `DOMAIN_NOT_ALLOWED`: Recipient domain not in allowed list
    - `EMAIL_SUPPRESSED`: Recipient is on suppression list
    - `SES_SEND_FAILED`: AWS SES failed to send the email
    - `EMAIL_SEND_FAILED`: Unexpected error during send
    - `DATABASE_ERROR`: Email sent but database save failed
    - `RATE_LIMIT_EXCEEDED`: Hourly email rate limit exceeded (429)
    - `SENDER_DOMAIN_NOT_VERIFIED`: Sender domain not verified in SES

    **Rate Limits:**
    - Configured via `EMAIL_RATE_LIMIT_PER_HOUR` setting
    - Default: 15 emails/hour (SES sandbox limit)

    **Example Request:**
    ```json
    {
      "to_email": "recipient@kubbly.com",
      "from_email": "sender@candidate-test.kubbly.com",
      "from_name": "SES Email Service",
      "subject": "Test Email",
      "html_content": "<h1>Hello!</h1><p>This is a test email.</p>",
      "text_content": "Hello! This is a test email.",
      "metadata": {"campaign_id": "test-001"}
    }
    ```

    **Example Response:**
    ```json
    {
      "success": true,
      "message_id": "123e4567-e89b-12d3-a456-426614174000",
      "ses_message_id": "0100018e...",
      "status": "sent",
      "created_at": "2024-01-15T10:30:00Z"
    }
    ```
    """
    return await email_service.send_email(db, request)
