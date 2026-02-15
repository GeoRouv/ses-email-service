"""HTML processing utilities for email tracking."""

import base64
import logging
from urllib.parse import quote

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# 1x1 transparent GIF (43 bytes) - base64 encoded
TRACKING_PIXEL_GIF = base64.b64decode(
    "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
)


def rewrite_urls(html: str, message_id: str, base_url: str) -> str:
    """
    Rewrite all URLs in HTML to track clicks.

    Replaces all <a href="..."> with tracking URLs that redirect through
    /api/track/click/{message_id}?url={encoded_original}

    Args:
        html: HTML content to process
        message_id: Message ID for tracking
        base_url: Base URL of the application

    Returns:
        HTML with rewritten URLs
    """
    try:
        soup = BeautifulSoup(html, "html.parser")

        # Find all anchor tags with href
        links_rewritten = 0
        for a_tag in soup.find_all("a", href=True):
            original_href = a_tag["href"]

            # Skip special links (mailto, tel, anchor)
            if original_href.startswith(("mailto:", "#", "tel:")):
                continue

            # Skip if already a tracking link
            if "/api/track/click/" in original_href:
                continue

            # Encode the original URL
            encoded_url = quote(original_href, safe="")

            # Replace with tracking URL
            tracking_url = f"{base_url}/api/track/click/{message_id}?url={encoded_url}"
            a_tag["href"] = tracking_url

            links_rewritten += 1

        if links_rewritten > 0:
            logger.debug(f"Rewrote {links_rewritten} URLs for message {message_id}")

        return str(soup)

    except Exception as e:
        logger.error(f"Error rewriting URLs: {str(e)}")
        # Return original HTML if processing fails
        return html


def inject_tracking_pixel(html: str, message_id: str, base_url: str) -> str:
    """
    Inject tracking pixel into HTML for open tracking.

    Inserts a 1x1 invisible image before </body> that tracks email opens.

    Args:
        html: HTML content to process
        message_id: Message ID for tracking
        base_url: Base URL of the application

    Returns:
        HTML with tracking pixel injected
    """
    try:
        pixel_url = f"{base_url}/api/track/open/{message_id}"
        pixel_tag = (
            f'<img src="{pixel_url}" width="1" height="1" alt="" '
            f'style="display:none;border:0;outline:0;" />'
        )

        # Insert before </body> if it exists
        if "</body>" in html.lower():
            # Case-insensitive replacement
            html = html.replace("</body>", f"{pixel_tag}</body>", 1)
            html = html.replace("</BODY>", f"{pixel_tag}</BODY>", 1)
        else:
            # No body tag, append at the end
            html = html + pixel_tag

        logger.debug(f"Injected tracking pixel for message {message_id}")

        return html

    except Exception as e:
        logger.error(f"Error injecting tracking pixel: {str(e)}")
        # Return original HTML if processing fails
        return html


def inject_unsubscribe_link(html: str, unsubscribe_url: str) -> str:
    """
    Inject an unsubscribe link at the bottom of the email HTML.

    Adds a small, muted unsubscribe link before </body> or at the end.
    This link goes directly to the unsubscribe page (not tracked).

    Args:
        html: HTML content to process
        unsubscribe_url: Full unsubscribe URL with signed token

    Returns:
        HTML with unsubscribe link injected
    """
    try:
        unsub_block = (
            '<div style="text-align:center;padding:20px 0 10px;'
            'font-size:12px;color:#999;">'
            '<a href="' + unsubscribe_url + '" '
            'style="color:#999;text-decoration:underline;">'
            "Unsubscribe from these emails</a>"
            "</div>"
        )

        if "</body>" in html.lower():
            html = html.replace("</body>", f"{unsub_block}</body>", 1)
            html = html.replace("</BODY>", f"{unsub_block}</BODY>", 1)
        else:
            html = html + unsub_block

        logger.debug("Injected unsubscribe link")
        return html

    except Exception as e:
        logger.error(f"Error injecting unsubscribe link: {str(e)}")
        return html


def process_email_html(
    html: str,
    message_id: str,
    base_url: str,
    unsubscribe_url: str | None = None,
) -> str:
    """
    Process email HTML for tracking (rewrite URLs + unsubscribe + pixel).

    Processing order:
    1. Rewrite URLs for click tracking
    2. Inject unsubscribe link (direct, not tracked)
    3. Inject tracking pixel

    Args:
        html: HTML content to process
        message_id: Message ID for tracking
        base_url: Base URL of the application
        unsubscribe_url: Optional unsubscribe URL to inject

    Returns:
        Processed HTML with tracking enabled
    """
    # Rewrite URLs for click tracking
    html = rewrite_urls(html, message_id, base_url)

    # Inject unsubscribe link (before pixel, not tracked)
    if unsubscribe_url:
        html = inject_unsubscribe_link(html, unsubscribe_url)

    # Inject tracking pixel for open tracking
    html = inject_tracking_pixel(html, message_id, base_url)

    return html


def sanitize_html(html: str) -> str:
    """
    Sanitize HTML to prevent XSS attacks.

    Note: Basic sanitization for now. In production, use a library like bleach.

    Args:
        html: HTML to sanitize

    Returns:
        Sanitized HTML
    """
    # BeautifulSoup already handles basic XSS by escaping
    # For production, consider using bleach or similar
    soup = BeautifulSoup(html, "html.parser")

    # Remove potentially dangerous tags
    dangerous_tags = ["script", "iframe", "object", "embed", "form"]
    for tag in soup.find_all(dangerous_tags):
        tag.decompose()

    return str(soup)
