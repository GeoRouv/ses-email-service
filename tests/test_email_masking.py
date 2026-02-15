"""Tests for email masking utility."""

from app.utils.email_masking import mask_email


class TestMaskEmail:
    def test_normal_email(self):
        assert mask_email("john@example.com") == "j***@example.com"

    def test_two_char_local(self):
        assert mask_email("ab@example.com") == "a***@example.com"

    def test_single_char_local(self):
        assert mask_email("a@example.com") == "***@example.com"

    def test_no_at_sign(self):
        assert mask_email("invalid") == "***"

    def test_long_local(self):
        result = mask_email("verylongusername@example.com")
        assert result == "v***@example.com"

    def test_preserves_domain(self):
        result = mask_email("user@subdomain.example.com")
        assert result == "u***@subdomain.example.com"
