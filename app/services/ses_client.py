"""AWS SES client wrapper for async email sending."""

import logging
from typing import Any

import aioboto3
from botocore.exceptions import ClientError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import settings

logger = logging.getLogger(__name__)


class SESError(Exception):
    """Base exception for SES operations."""

    pass


class SESClient:
    """Async wrapper for AWS SES operations."""

    def __init__(self):
        """Initialize SES client with AWS credentials from settings."""
        self.session = aioboto3.Session(
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_REGION,
        )
        self.configuration_set = settings.SES_CONFIGURATION_SET

    @retry(
        retry=retry_if_exception_type((ClientError,)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def send_email(
        self,
        source: str,
        to: str,
        subject: str,
        html: str,
        text: str | None = None,
        message_id: str | None = None,
    ) -> str:
        """
        Send an email via AWS SES with retry logic.

        Args:
            source: Sender email address (e.g., "sender@example.com" or "Name <email@example.com>")
            to: Recipient email address
            subject: Email subject
            html: HTML email body
            text: Plain text email body (optional, falls back to stripped HTML)
            message_id: Optional message ID to tag in SES

        Returns:
            SES MessageId (used for webhook correlation)

        Raises:
            SESError: If email sending fails after retries
        """
        try:
            async with self.session.client("ses") as ses:
                # Build email message
                message: dict[str, Any] = {
                    "Subject": {"Data": subject},
                    "Body": {"Html": {"Data": html}},
                }

                # Add text body if provided
                if text:
                    message["Body"]["Text"] = {"Data": text}

                # Build send_email params
                params: dict[str, Any] = {
                    "Source": source,
                    "Destination": {"ToAddresses": [to]},
                    "Message": message,
                }

                # Add configuration set for tracking
                if self.configuration_set:
                    params["ConfigurationSetName"] = self.configuration_set

                # Add tags for correlation
                if message_id:
                    params["Tags"] = [
                        {"Name": "AppMessageId", "Value": message_id},
                    ]

                logger.info(f"Sending email to {to} with subject: {subject}")

                response = await ses.send_email(**params)

                ses_message_id = response["MessageId"]
                logger.info(f"Email sent successfully. SES MessageId: {ses_message_id}")

                return ses_message_id

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))

            logger.error(f"SES send failed: {error_code} - {error_message}")

            # Map SES errors to friendly messages
            if error_code == "MessageRejected":
                raise SESError(f"Email rejected by SES: {error_message}")
            elif error_code == "MailFromDomainNotVerified":
                raise SESError(f"Sender domain not verified: {error_message}")
            elif error_code == "ConfigurationSetDoesNotExist":
                raise SESError(f"Configuration set not found: {error_message}")
            elif error_code == "AccountSendingPausedException":
                raise SESError("Account sending is paused")
            else:
                raise SESError(f"SES error ({error_code}): {error_message}")

        except Exception as e:
            logger.error(f"Unexpected error sending email: {str(e)}")
            raise SESError(f"Failed to send email: {str(e)}")

    async def verify_domain(self, domain: str) -> str:
        """
        Initiate domain verification in SES.

        Args:
            domain: Domain to verify

        Returns:
            Verification token

        Raises:
            SESError: If verification initiation fails
        """
        try:
            async with self.session.client("ses") as ses:
                response = await ses.verify_domain_identity(Domain=domain)
                return response["VerificationToken"]
        except ClientError as e:
            error_message = e.response.get("Error", {}).get("Message", str(e))
            raise SESError(f"Failed to initiate domain verification: {error_message}")

    async def get_domain_verification_status(self, domain: str) -> dict[str, Any]:
        """
        Get domain verification status.

        Args:
            domain: Domain to check

        Returns:
            Dictionary with verification status

        Raises:
            SESError: If status check fails
        """
        try:
            async with self.session.client("ses") as ses:
                response = await ses.get_identity_verification_attributes(
                    Identities=[domain]
                )
                return response.get("VerificationAttributes", {}).get(domain, {})
        except ClientError as e:
            error_message = e.response.get("Error", {}).get("Message", str(e))
            raise SESError(f"Failed to get domain verification status: {error_message}")


# Global SES client instance
ses_client = SESClient()
