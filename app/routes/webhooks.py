"""Webhook API routes for SNS/SES events."""

import json
import logging

import httpx
from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.schemas.common import raise_api_error
from app.schemas.webhook import SNSMessage, WebhookResponse
from app.services import webhook_service
from app.utils.sns_validator import verify_sns_signature

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/webhooks/ses", response_model=WebhookResponse)
async def handle_ses_webhook(
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> WebhookResponse:
    """
    Handle SES events delivered via SNS.

    This endpoint:
    1. Receives SNS messages (SubscriptionConfirmation or Notification)
    2. Validates SNS signature for security
    3. Auto-confirms SNS subscriptions
    4. Parses SES events from SNS Message field (double JSON parsing)
    5. Routes events to appropriate handlers
    6. Updates message status and stores events in database
    7. Auto-suppresses on hard bounces and complaints

    **SNS Message Types:**
    - `SubscriptionConfirmation`: Auto-confirmed by fetching SubscribeURL
    - `Notification`: Contains SES event in Message field (JSON string)

    **SES Event Types Handled:**
    - `Delivery`: Message delivered successfully
    - `Bounce`: Message bounced (permanent or transient)
    - `Complaint`: Recipient marked as spam/complaint
    - `DeliveryDelay`: Temporary delivery delay
    - `Reject`: Message rejected by SES

    **State Transitions:**
    - `sent → delivered` (on Delivery)
    - `sent → bounced` (on Bounce)
    - `sent → deferred` (on DeliveryDelay)
    - `sent → rejected` (on Reject)
    - `deferred → delivered` (on Delivery after delay)
    - `deferred → bounced` (on Bounce after delay)
    - `delivered → complained` (on Complaint)

    **Auto-Suppression:**
    - Hard bounces: Automatically added to suppression list
    - Complaints: Automatically added to suppression list

    **Security:**
    - All SNS messages are signature-verified using AWS certificates
    - Only messages from valid SNS endpoints are processed

    **Example SNS Notification:**
    ```json
    {
      "Type": "Notification",
      "MessageId": "sns-msg-id",
      "TopicArn": "arn:aws:sns:...",
      "Message": "{\"eventType\":\"Delivery\",\"mail\":{...},\"delivery\":{...}}",
      "Timestamp": "2024-01-15T10:30:00.000Z",
      "Signature": "...",
      "SigningCertURL": "https://sns.us-east-1.amazonaws.com/..."
    }
    ```
    """
    try:
        # Get raw body
        body_bytes = await request.body()
        body_str = body_bytes.decode("utf-8")

        # Parse SNS message
        try:
            sns_message = json.loads(body_str)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in webhook body: {str(e)}")
            raise_api_error(
                code="INVALID_JSON",
                message="Invalid JSON payload",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # Validate SNS message structure
        try:
            sns_msg_validated = SNSMessage(**sns_message)
        except Exception as e:
            logger.error(f"Invalid SNS message structure: {str(e)}")
            raise_api_error(
                code="INVALID_SNS_MESSAGE",
                message=f"Invalid SNS message structure: {str(e)}",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # Verify SNS signature
        try:
            is_valid = await verify_sns_signature(sns_message)
            if not is_valid:
                logger.warning("SNS signature verification failed")
                raise_api_error(
                    code="INVALID_SIGNATURE",
                    message="SNS signature verification failed",
                    status_code=status.HTTP_403_FORBIDDEN,
                )
        except ValueError as e:
            logger.error(f"Signature verification error: {str(e)}")
            raise_api_error(
                code="SIGNATURE_VERIFICATION_ERROR",
                message=str(e),
                status_code=status.HTTP_403_FORBIDDEN,
            )

        logger.info(f"Received SNS message type: {sns_msg_validated.Type}")

        # Handle subscription confirmation
        if sns_msg_validated.Type == "SubscriptionConfirmation":
            if not sns_msg_validated.SubscribeURL:
                raise_api_error(
                    code="MISSING_SUBSCRIBE_URL",
                    message="SubscribeURL missing from SubscriptionConfirmation",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            # Auto-confirm subscription
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        sns_msg_validated.SubscribeURL,
                        timeout=10.0,
                    )
                    response.raise_for_status()

                logger.info(f"SNS subscription confirmed: {sns_msg_validated.MessageId}")

                return WebhookResponse(
                    success=True,
                    message="Subscription confirmed",
                    event_type="SubscriptionConfirmation",
                    message_id=sns_msg_validated.MessageId,
                )

            except Exception as e:
                logger.error(f"Failed to confirm subscription: {str(e)}")
                raise_api_error(
                    code="SUBSCRIPTION_CONFIRMATION_FAILED",
                    message=f"Failed to confirm subscription: {str(e)}",
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        # Handle notification (SES event)
        elif sns_msg_validated.Type == "Notification":
            # Parse SES event from Message field (it's JSON-stringified)
            try:
                ses_event = json.loads(sns_msg_validated.Message)
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON in SNS Message field: {str(e)}")
                raise_api_error(
                    code="INVALID_SES_EVENT",
                    message="Invalid JSON in SES event",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            event_type = ses_event.get("eventType", "Unknown")
            logger.info(f"Processing SES event: {event_type}")

            # Process SES event
            try:
                await webhook_service.process_ses_event(db, ses_event)

                return WebhookResponse(
                    success=True,
                    message=f"SES event processed: {event_type}",
                    event_type=event_type,
                    message_id=sns_msg_validated.MessageId,
                )

            except Exception as e:
                logger.error(f"Error processing SES event: {str(e)}", exc_info=True)
                # Don't fail the webhook - just log the error
                # This ensures SNS doesn't retry indefinitely
                return WebhookResponse(
                    success=True,
                    message=f"Event logged with errors: {str(e)}",
                    event_type=event_type,
                    message_id=sns_msg_validated.MessageId,
                )

        # Unknown message type
        else:
            logger.warning(f"Unknown SNS message type: {sns_msg_validated.Type}")
            return WebhookResponse(
                success=True,
                message=f"Unknown message type: {sns_msg_validated.Type}",
                message_id=sns_msg_validated.MessageId,
            )

    except Exception as e:
        # Catch-all to prevent 500 errors from blocking SNS
        logger.error(f"Unexpected error in webhook handler: {str(e)}", exc_info=True)
        return WebhookResponse(
            success=True,
            message=f"Webhook received with errors: {str(e)}",
        )
