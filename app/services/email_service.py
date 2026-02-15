"""Email sending service with business logic."""

import logging
from datetime import datetime
from uuid import uuid4

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.message import Message
from app.models.suppression import Suppression
from app.schemas.common import raise_api_error
from app.schemas.email import SendEmailRequest, SendEmailResponse
from app.services.ses_client import SESError, ses_client
from app.utils.email_validator import validate_domain_allowed, validate_email
from app.utils.html_processor import process_email_html

logger = logging.getLogger(__name__)


async def check_suppression(db: AsyncSession, email: str) -> bool:
    """
    Check if an email address is suppressed.

    Args:
        db: Database session
        email: Email address to check

    Returns:
        True if suppressed, False otherwise
    """
    result = await db.execute(
        select(Suppression).where(Suppression.email == email.lower())
    )
    suppression = result.scalar_one_or_none()
    return suppression is not None


async def send_email(db: AsyncSession, request: SendEmailRequest) -> SendEmailResponse:
    """
    Send an email via SES with validation and suppression checks.

    Args:
        db: Database session
        request: Email send request

    Returns:
        SendEmailResponse with message details

    Raises:
        HTTPException: If validation fails or sending fails
    """
    # Validate recipient email format
    is_valid, error_msg = validate_email(request.to_email)
    if not is_valid:
        logger.warning(f"Invalid recipient email: {request.to_email} - {error_msg}")
        raise_api_error(
            code="INVALID_RECIPIENT_EMAIL",
            message=error_msg or "Invalid recipient email address",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # Validate sender email format
    is_valid, error_msg = validate_email(request.from_email)
    if not is_valid:
        logger.warning(f"Invalid sender email: {request.from_email} - {error_msg}")
        raise_api_error(
            code="INVALID_SENDER_EMAIL",
            message=error_msg or "Invalid sender email address",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # Check if recipient domain is allowed
    is_allowed, error_msg = validate_domain_allowed(
        request.to_email, settings.allowed_domains_list
    )
    if not is_allowed:
        logger.warning(f"Domain not allowed: {request.to_email}")
        raise_api_error(
            code="DOMAIN_NOT_ALLOWED",
            message=error_msg or "Recipient domain is not allowed",
            status_code=status.HTTP_403_FORBIDDEN,
            details={"allowed_domains": settings.allowed_domains_list},
        )

    # Check suppression list
    is_suppressed = await check_suppression(db, request.to_email)
    if is_suppressed:
        logger.warning(f"Email suppressed: {request.to_email}")
        raise_api_error(
            code="EMAIL_SUPPRESSED",
            message=f"Cannot send to {request.to_email} - address is suppressed",
            status_code=status.HTTP_400_BAD_REQUEST,
            details={"suppressed_email": request.to_email},
        )

    # Create message record
    message = Message(
        id=uuid4(),
        to_email=request.to_email.lower(),
        from_email=request.from_email.lower(),
        from_name=request.from_name,
        subject=request.subject,
        html_content=request.html_content,
        text_content=request.text_content,
        status="sent",
        message_metadata=request.metadata,
        ses_message_id="",  # Will be updated after SES send
    )

    # Process HTML for tracking (rewrite URLs + inject pixel)
    processed_html = process_email_html(
        html=request.html_content,
        message_id=str(message.id),
        base_url=settings.APP_BASE_URL,
    )

    # Update message with processed HTML
    message.html_content = processed_html

    # Build sender address (with name if provided)
    if request.from_name:
        source = f"{request.from_name} <{request.from_email}>"
    else:
        source = request.from_email

    # Send via SES
    try:
        ses_message_id = await ses_client.send_email(
            source=source,
            to=request.to_email,
            subject=request.subject,
            html=processed_html,  # Use processed HTML with tracking
            text=request.text_content,
            message_id=str(message.id),
        )

        # Strip angle brackets if present (SES sometimes includes them)
        if ses_message_id.startswith("<") and ses_message_id.endswith(">"):
            ses_message_id = ses_message_id[1:-1]

        message.ses_message_id = ses_message_id

        logger.info(
            f"Email sent successfully: message_id={message.id}, "
            f"ses_message_id={ses_message_id}, to={request.to_email}"
        )

    except SESError as e:
        logger.error(f"SES error while sending email: {str(e)}")
        raise_api_error(
            code="SES_SEND_FAILED",
            message=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    except Exception as e:
        logger.error(f"Unexpected error sending email: {str(e)}")
        raise_api_error(
            code="EMAIL_SEND_FAILED",
            message="Failed to send email due to an unexpected error",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            details={"error": str(e)},
        )

    # Save to database
    try:
        db.add(message)
        await db.flush()  # Flush to get the created_at timestamp
        await db.refresh(message)

        logger.info(f"Message saved to database: {message.id}")

    except Exception as e:
        logger.error(f"Failed to save message to database: {str(e)}")
        raise_api_error(
            code="DATABASE_ERROR",
            message="Email sent but failed to save to database",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            details={"ses_message_id": ses_message_id},
        )

    # Return response
    return SendEmailResponse(
        success=True,
        message_id=message.id,
        ses_message_id=message.ses_message_id,
        status=message.status,
        created_at=message.created_at,
    )
