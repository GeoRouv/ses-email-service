"""Email masking utility for privacy in unsubscribe pages."""


def mask_email(email: str) -> str:
    """
    Mask an email address for display on unsubscribe pages.

    Examples:
        john@example.com    → j***@example.com
        ab@example.com      → a***@example.com
        a@example.com       → ***@example.com

    Args:
        email: Full email address

    Returns:
        Masked email address
    """
    if "@" not in email:
        return "***"

    local, domain = email.split("@", 1)

    if len(local) > 1:
        masked_local = local[0] + "***"
    else:
        masked_local = "***"

    return f"{masked_local}@{domain}"
