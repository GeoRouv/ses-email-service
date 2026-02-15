"""AWS SES client wrapper for async email sending."""

import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
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
        unsubscribe_url: str | None = None,
    ) -> str:
        """
        Send an email via AWS SES with retry logic.

        Uses send_raw_email when unsubscribe_url is provided (to include
        List-Unsubscribe header), otherwise uses send_email for simplicity.

        Args:
            source: Sender email address (e.g., "sender@example.com" or "Name <email@example.com>")
            to: Recipient email address
            subject: Email subject
            html: HTML email body
            text: Plain text email body (optional)
            message_id: Optional message ID to tag in SES
            unsubscribe_url: Optional unsubscribe URL for List-Unsubscribe header

        Returns:
            SES MessageId (used for webhook correlation)

        Raises:
            SESError: If email sending fails after retries
        """
        try:
            async with self.session.client("ses") as ses:
                if unsubscribe_url:
                    # Use send_raw_email to include List-Unsubscribe header
                    ses_message_id = await self._send_raw_email(
                        ses, source, to, subject, html, text,
                        message_id, unsubscribe_url,
                    )
                else:
                    # Use simple send_email API
                    ses_message_id = await self._send_simple_email(
                        ses, source, to, subject, html, text, message_id,
                    )

                logger.info(f"Email sent successfully. SES MessageId: {ses_message_id}")
                return ses_message_id

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))

            logger.error(f"SES send failed: {error_code} - {error_message}")

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

    async def _send_simple_email(
        self,
        ses: Any,
        source: str,
        to: str,
        subject: str,
        html: str,
        text: str | None,
        message_id: str | None,
    ) -> str:
        """Send using the simple SES send_email API."""
        message: dict[str, Any] = {
            "Subject": {"Data": subject},
            "Body": {"Html": {"Data": html}},
        }

        if text:
            message["Body"]["Text"] = {"Data": text}

        params: dict[str, Any] = {
            "Source": source,
            "Destination": {"ToAddresses": [to]},
            "Message": message,
        }

        if self.configuration_set:
            params["ConfigurationSetName"] = self.configuration_set

        if message_id:
            params["Tags"] = [
                {"Name": "AppMessageId", "Value": message_id},
            ]

        logger.info(f"Sending email to {to} with subject: {subject}")
        response = await ses.send_email(**params)
        return response["MessageId"]

    async def _send_raw_email(
        self,
        ses: Any,
        source: str,
        to: str,
        subject: str,
        html: str,
        text: str | None,
        message_id: str | None,
        unsubscribe_url: str,
    ) -> str:
        """Send using SES send_raw_email API to include custom headers."""
        # Build MIME message
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = source
        msg["To"] = to
        msg["List-Unsubscribe"] = f"<{unsubscribe_url}>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

        # Add text part
        if text:
            msg.attach(MIMEText(text, "plain", "utf-8"))

        # Add HTML part
        msg.attach(MIMEText(html, "html", "utf-8"))

        params: dict[str, Any] = {
            "Source": source,
            "Destinations": [to],
            "RawMessage": {"Data": msg.as_string()},
        }

        if self.configuration_set:
            params["ConfigurationSetName"] = self.configuration_set

        if message_id:
            params["Tags"] = [
                {"Name": "AppMessageId", "Value": message_id},
            ]

        logger.info(f"Sending raw email to {to} with subject: {subject}")
        response = await ses.send_raw_email(**params)
        return response["MessageId"]

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
