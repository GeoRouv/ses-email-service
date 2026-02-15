"""SNS signature validation utilities."""

import base64
import logging
import re
from typing import Any
from urllib.parse import urlparse

import httpx
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

logger = logging.getLogger(__name__)

# Cache for signing certificates (URL -> certificate)
_cert_cache: dict[str, x509.Certificate] = {}


def is_valid_sns_url(url: str) -> bool:
    """
    Validate that the URL is a legitimate SNS endpoint.

    Args:
        url: URL to validate

    Returns:
        True if URL is a valid SNS endpoint
    """
    parsed = urlparse(url)

    # Must be HTTPS
    if parsed.scheme != "https":
        return False

    # Must be an SNS domain
    # Pattern: sns.<region>.amazonaws.com or sns.<region>.amazonaws.com.cn
    pattern = r"^sns\.[a-z0-9-]+\.amazonaws\.com(\.cn)?$"
    if not re.match(pattern, parsed.netloc):
        return False

    return True


async def fetch_signing_certificate(cert_url: str) -> x509.Certificate:
    """
    Fetch and parse the SNS signing certificate.

    Args:
        cert_url: URL to the signing certificate

    Returns:
        Parsed X.509 certificate

    Raises:
        ValueError: If URL is invalid or certificate cannot be fetched
    """
    # Check cache first
    if cert_url in _cert_cache:
        logger.debug(f"Using cached certificate for {cert_url}")
        return _cert_cache[cert_url]

    # Validate URL
    if not is_valid_sns_url(cert_url):
        raise ValueError(f"Invalid SNS certificate URL: {cert_url}")

    # Fetch certificate
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(cert_url, timeout=10.0)
            response.raise_for_status()

            cert_pem = response.content

            # Parse certificate
            certificate = x509.load_pem_x509_certificate(cert_pem)

            # Cache it
            _cert_cache[cert_url] = certificate

            logger.info(f"Fetched and cached certificate from {cert_url}")
            return certificate

    except Exception as e:
        logger.error(f"Failed to fetch certificate from {cert_url}: {str(e)}")
        raise ValueError(f"Failed to fetch signing certificate: {str(e)}")


def build_signature_string(message: dict[str, Any]) -> bytes:
    """
    Build the canonical string to sign for SNS message verification.

    The fields and their order depend on the message Type.

    Args:
        message: SNS message dictionary

    Returns:
        UTF-8 encoded string to verify against signature
    """
    msg_type = message.get("Type")

    # Fields for Notification messages
    if msg_type == "Notification":
        fields = [
            "Message",
            "MessageId",
            "Subject",  # Optional
            "Timestamp",
            "TopicArn",
            "Type",
        ]
    # Fields for SubscriptionConfirmation and UnsubscribeConfirmation
    elif msg_type in ("SubscriptionConfirmation", "UnsubscribeConfirmation"):
        fields = [
            "Message",
            "MessageId",
            "SubscribeURL",
            "Timestamp",
            "Token",
            "TopicArn",
            "Type",
        ]
    else:
        raise ValueError(f"Unknown SNS message type: {msg_type}")

    # Build canonical string
    parts = []
    for field in fields:
        value = message.get(field)
        if value is not None:  # Include field only if present
            parts.append(f"{field}\n{value}\n")

    return "".join(parts).encode("utf-8")


async def verify_sns_signature(message: dict[str, Any]) -> bool:
    """
    Verify the SNS message signature.

    Args:
        message: SNS message dictionary with Signature and SigningCertURL

    Returns:
        True if signature is valid

    Raises:
        ValueError: If message is missing required fields or validation fails
    """
    # Check required fields
    required_fields = ["Signature", "SigningCertURL", "Type", "MessageId"]
    for field in required_fields:
        if field not in message:
            raise ValueError(f"Missing required field: {field}")

    # Get signature and certificate URL
    signature_b64 = message["Signature"]
    cert_url = message["SigningCertURL"]

    try:
        # Decode signature
        signature = base64.b64decode(signature_b64)

        # Fetch certificate
        certificate = await fetch_signing_certificate(cert_url)

        # Build string to sign
        string_to_sign = build_signature_string(message)

        # Get public key from certificate
        public_key = certificate.public_key()

        # Verify signature
        try:
            public_key.verify(
                signature,
                string_to_sign,
                padding.PKCS1v15(),
                hashes.SHA1(),  # SNS uses SHA1 for signing
            )
            logger.info(f"SNS signature verified for message {message['MessageId']}")
            return True

        except InvalidSignature:
            logger.warning(f"Invalid SNS signature for message {message['MessageId']}")
            return False

    except Exception as e:
        logger.error(f"Error verifying SNS signature: {str(e)}")
        raise ValueError(f"Signature verification failed: {str(e)}")


def clear_certificate_cache() -> None:
    """Clear the certificate cache. Useful for testing."""
    global _cert_cache
    _cert_cache = {}
