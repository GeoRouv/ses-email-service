"""Tests for SNS signature validation utilities."""

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.exceptions import InvalidSignature

from app.utils import sns_validator as sns_mod
from app.utils.sns_validator import (
    build_signature_string,
    clear_certificate_cache,
    fetch_signing_certificate,
    is_valid_sns_url,
    verify_sns_signature,
)


class TestIsValidSnsUrl:
    def test_valid_us_east_url(self):
        url = "https://sns.us-east-1.amazonaws.com/SimpleNotificationService-abc123.pem"
        assert is_valid_sns_url(url) is True

    def test_valid_eu_west_url(self):
        url = "https://sns.eu-west-1.amazonaws.com/cert.pem"
        assert is_valid_sns_url(url) is True

    def test_valid_china_region(self):
        url = "https://sns.cn-north-1.amazonaws.com.cn/cert.pem"
        assert is_valid_sns_url(url) is True

    def test_invalid_http(self):
        url = "http://sns.us-east-1.amazonaws.com/cert.pem"
        assert is_valid_sns_url(url) is False

    def test_invalid_domain(self):
        url = "https://evil.com/cert.pem"
        assert is_valid_sns_url(url) is False

    def test_invalid_subdomain(self):
        url = "https://notsns.us-east-1.amazonaws.com/cert.pem"
        assert is_valid_sns_url(url) is False


class TestBuildSignatureString:
    def test_notification_fields(self):
        message = {
            "Type": "Notification",
            "MessageId": "msg-123",
            "Message": "test message",
            "Timestamp": "2024-01-15T10:30:00.000Z",
            "TopicArn": "arn:aws:sns:us-east-1:123456:test",
        }
        result = build_signature_string(message)
        assert b"Message\ntest message\n" in result
        assert b"MessageId\nmsg-123\n" in result
        assert b"Timestamp\n" in result
        assert b"TopicArn\n" in result
        assert b"Type\nNotification\n" in result

    def test_notification_with_subject(self):
        message = {
            "Type": "Notification",
            "MessageId": "msg-123",
            "Message": "test",
            "Subject": "Test Subject",
            "Timestamp": "2024-01-15T10:30:00.000Z",
            "TopicArn": "arn:aws:sns:us-east-1:123456:test",
        }
        result = build_signature_string(message)
        assert b"Subject\nTest Subject\n" in result

    def test_subscription_confirmation_fields(self):
        message = {
            "Type": "SubscriptionConfirmation",
            "MessageId": "msg-123",
            "Message": "confirm",
            "SubscribeURL": "https://sns.us-east-1.amazonaws.com/confirm",
            "Timestamp": "2024-01-15T10:30:00.000Z",
            "Token": "abc123",
            "TopicArn": "arn:aws:sns:us-east-1:123456:test",
        }
        result = build_signature_string(message)
        assert b"SubscribeURL\n" in result
        assert b"Token\nabc123\n" in result

    def test_unknown_type_raises(self):
        message = {"Type": "UnknownType"}
        try:
            build_signature_string(message)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "Unknown SNS message type" in str(e)

    def test_optional_fields_excluded(self):
        message = {
            "Type": "Notification",
            "MessageId": "msg-123",
            "Message": "test",
            "Timestamp": "2024-01-15T10:30:00.000Z",
            "TopicArn": "arn:aws:sns:us-east-1:123456:test",
            # No Subject field
        }
        result = build_signature_string(message)
        assert b"Subject\n" not in result


class TestClearCertificateCache:
    def test_clears_cache(self):
        # Populate cache with a dummy entry
        sns_mod._cert_cache["https://sns.us-east-1.amazonaws.com/test.pem"] = "dummy"
        assert len(sns_mod._cert_cache) > 0

        clear_certificate_cache()
        assert len(sns_mod._cert_cache) == 0


class TestFetchSigningCertificate:
    async def test_invalid_url_raises(self):
        with pytest.raises(ValueError, match="Invalid SNS certificate URL"):
            await fetch_signing_certificate("https://evil.com/cert.pem")

    @patch("app.utils.sns_validator.httpx.AsyncClient")
    async def test_fetches_and_caches(self, mock_client_cls):
        clear_certificate_cache()

        # Create a self-signed cert PEM for testing
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        import datetime

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test")])
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
            .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1))
            .sign(key, hashes.SHA256())
        )
        cert_pem = cert.public_bytes(serialization.Encoding.PEM)

        # Mock httpx response
        mock_response = MagicMock()
        mock_response.content = cert_pem
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        cert_url = "https://sns.us-east-1.amazonaws.com/cert.pem"
        result = await fetch_signing_certificate(cert_url)

        assert isinstance(result, x509.Certificate)
        # Should be cached now
        assert cert_url in sns_mod._cert_cache

    async def test_returns_cached_cert(self):
        cert_url = "https://sns.us-east-1.amazonaws.com/cached.pem"
        dummy_cert = MagicMock()
        sns_mod._cert_cache[cert_url] = dummy_cert

        result = await fetch_signing_certificate(cert_url)
        assert result is dummy_cert

        # Cleanup
        clear_certificate_cache()

    @patch("app.utils.sns_validator.httpx.AsyncClient")
    async def test_fetch_failure_raises(self, mock_client_cls):
        clear_certificate_cache()

        mock_client = AsyncMock()
        mock_client.get.side_effect = Exception("Connection refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with pytest.raises(ValueError, match="Failed to fetch signing certificate"):
            await fetch_signing_certificate("https://sns.us-east-1.amazonaws.com/cert.pem")


class TestVerifySnSSignature:
    async def test_missing_signature_field(self):
        message = {"Type": "Notification", "MessageId": "123", "SigningCertURL": "url"}
        with pytest.raises(ValueError, match="Missing required field: Signature"):
            await verify_sns_signature(message)

    async def test_missing_signing_cert_url(self):
        message = {"Type": "Notification", "MessageId": "123", "Signature": "abc"}
        with pytest.raises(ValueError, match="Missing required field: SigningCertURL"):
            await verify_sns_signature(message)

    async def test_missing_type(self):
        message = {"MessageId": "123", "Signature": "abc", "SigningCertURL": "url"}
        with pytest.raises(ValueError, match="Missing required field: Type"):
            await verify_sns_signature(message)

    async def test_missing_message_id(self):
        message = {"Type": "Notification", "Signature": "abc", "SigningCertURL": "url"}
        with pytest.raises(ValueError, match="Missing required field: MessageId"):
            await verify_sns_signature(message)

    @patch("app.utils.sns_validator.fetch_signing_certificate")
    async def test_valid_signature_returns_true(self, mock_fetch):
        # Create a real key pair and sign a message
        from cryptography.hazmat.primitives.asymmetric import rsa, padding
        from cryptography.hazmat.primitives import hashes

        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_key = private_key.public_key()

        message = {
            "Type": "Notification",
            "MessageId": "msg-123",
            "Message": "test",
            "Timestamp": "2024-01-15T10:30:00.000Z",
            "TopicArn": "arn:aws:sns:us-east-1:123456:test",
            "SigningCertURL": "https://sns.us-east-1.amazonaws.com/cert.pem",
        }

        # Build the string and sign it
        string_to_sign = build_signature_string(message)
        signature = private_key.sign(string_to_sign, padding.PKCS1v15(), hashes.SHA1())
        message["Signature"] = base64.b64encode(signature).decode()

        # Mock certificate that returns our public key
        mock_cert = MagicMock()
        mock_cert.public_key.return_value = public_key
        mock_fetch.return_value = mock_cert

        result = await verify_sns_signature(message)
        assert result is True

    @patch("app.utils.sns_validator.fetch_signing_certificate")
    async def test_invalid_signature_returns_false(self, mock_fetch):
        from cryptography.hazmat.primitives.asymmetric import rsa

        # Use one key to sign but a different key to verify
        signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        verify_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

        message = {
            "Type": "Notification",
            "MessageId": "msg-123",
            "Message": "test",
            "Timestamp": "2024-01-15T10:30:00.000Z",
            "TopicArn": "arn:aws:sns:us-east-1:123456:test",
            "SigningCertURL": "https://sns.us-east-1.amazonaws.com/cert.pem",
        }

        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives import hashes

        string_to_sign = build_signature_string(message)
        # Sign with one key
        signature = signing_key.sign(string_to_sign, padding.PKCS1v15(), hashes.SHA1())
        message["Signature"] = base64.b64encode(signature).decode()

        # But verify with a different key
        mock_cert = MagicMock()
        mock_cert.public_key.return_value = verify_key.public_key()
        mock_fetch.return_value = mock_cert

        result = await verify_sns_signature(message)
        assert result is False

    @patch("app.utils.sns_validator.fetch_signing_certificate")
    async def test_fetch_error_raises_value_error(self, mock_fetch):
        mock_fetch.side_effect = ValueError("Failed to fetch")

        message = {
            "Type": "Notification",
            "MessageId": "msg-123",
            "Message": "test",
            "Timestamp": "2024-01-15T10:30:00.000Z",
            "TopicArn": "arn:aws:sns:us-east-1:123456:test",
            "SigningCertURL": "https://sns.us-east-1.amazonaws.com/cert.pem",
            "Signature": base64.b64encode(b"fake").decode(),
        }

        with pytest.raises(ValueError, match="Signature verification failed"):
            await verify_sns_signature(message)
