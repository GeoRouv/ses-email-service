"""Email validation utilities."""

import re
from typing import Tuple

# RFC 5322 simplified email regex
EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}"
    r"[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$"
)


def validate_email(email: str) -> Tuple[bool, str | None]:
    """
    Validate email address format.

    Args:
        email: Email address to validate

    Returns:
        Tuple of (is_valid, error_message)
        If valid, error_message is None
    """
    if not email:
        return False, "Email address is required"

    email = email.strip()

    if len(email) > 254:
        return False, "Email address is too long (max 254 characters)"

    if not EMAIL_REGEX.match(email):
        return False, "Invalid email address format"

    # Check local part (before @)
    local, _, domain = email.partition("@")

    if len(local) > 64:
        return False, "Email local part is too long (max 64 characters)"

    if not domain:
        return False, "Email address must contain a domain"

    if len(domain) > 253:
        return False, "Email domain is too long (max 253 characters)"

    # Check for consecutive dots
    if ".." in email:
        return False, "Email address cannot contain consecutive dots"

    # Check domain has at least one dot
    if "." not in domain:
        return False, "Email domain must contain at least one dot"

    return True, None


def validate_domain_allowed(email: str, allowed_domains: list[str]) -> Tuple[bool, str | None]:
    """
    Check if email domain is in allowed list.

    Args:
        email: Email address to check
        allowed_domains: List of allowed domains

    Returns:
        Tuple of (is_allowed, error_message)
    """
    if not allowed_domains:
        return True, None

    _, _, domain = email.partition("@")
    domain = domain.lower()

    for allowed in allowed_domains:
        allowed = allowed.lower().strip()
        if domain == allowed or domain.endswith(f".{allowed}"):
            return True, None

    return False, f"Email domain not allowed. Allowed domains: {', '.join(allowed_domains)}"


def extract_domain(email: str) -> str:
    """
    Extract domain from email address.

    Args:
        email: Email address

    Returns:
        Domain part of the email
    """
    _, _, domain = email.partition("@")
    return domain.lower()
