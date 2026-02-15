"""Tests for email validation utilities."""

from app.utils.email_validator import extract_domain, validate_domain_allowed, validate_email


class TestValidateEmail:
    def test_valid_email(self):
        is_valid, error = validate_email("user@example.com")
        assert is_valid is True
        assert error is None

    def test_valid_email_with_dots(self):
        is_valid, error = validate_email("first.last@example.com")
        assert is_valid is True

    def test_valid_email_with_plus(self):
        is_valid, error = validate_email("user+tag@example.com")
        assert is_valid is True

    def test_empty_email(self):
        is_valid, error = validate_email("")
        assert is_valid is False
        assert "required" in error.lower()

    def test_no_at_sign(self):
        is_valid, error = validate_email("userexample.com")
        assert is_valid is False

    def test_too_long_email(self):
        is_valid, error = validate_email("a" * 255 + "@example.com")
        assert is_valid is False
        assert "too long" in error.lower()

    def test_too_long_local_part(self):
        is_valid, error = validate_email("a" * 65 + "@example.com")
        assert is_valid is False
        assert "local part" in error.lower()

    def test_consecutive_dots(self):
        is_valid, error = validate_email("user..name@example.com")
        assert is_valid is False
        assert "consecutive dots" in error.lower()

    def test_no_domain_dot(self):
        is_valid, error = validate_email("user@localhost")
        assert is_valid is False
        assert "dot" in error.lower()

    def test_whitespace_stripped(self):
        is_valid, error = validate_email("  user@example.com  ")
        assert is_valid is True


class TestValidateDomainAllowed:
    def test_allowed_domain(self):
        is_allowed, error = validate_domain_allowed(
            "user@example.com", ["example.com"]
        )
        assert is_allowed is True

    def test_subdomain_allowed(self):
        is_allowed, error = validate_domain_allowed(
            "user@sub.example.com", ["example.com"]
        )
        assert is_allowed is True

    def test_domain_not_allowed(self):
        is_allowed, error = validate_domain_allowed(
            "user@other.com", ["example.com"]
        )
        assert is_allowed is False
        assert "not allowed" in error.lower()

    def test_empty_allowed_list(self):
        is_allowed, error = validate_domain_allowed(
            "user@anything.com", []
        )
        assert is_allowed is True

    def test_case_insensitive(self):
        is_allowed, error = validate_domain_allowed(
            "user@EXAMPLE.COM", ["example.com"]
        )
        assert is_allowed is True


class TestExtractDomain:
    def test_extract_domain(self):
        assert extract_domain("user@example.com") == "example.com"

    def test_extract_domain_lowercase(self):
        assert extract_domain("user@EXAMPLE.COM") == "example.com"

    def test_extract_subdomain(self):
        assert extract_domain("user@sub.example.com") == "sub.example.com"
