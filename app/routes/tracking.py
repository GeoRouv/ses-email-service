"""Tracking API routes for click and open events."""

import logging
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.services import tracking_service
from app.utils.html_processor import TRACKING_PIXEL_GIF

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/track/click/{tracking_id}")
async def track_click(
    tracking_id: str,
    url: str = Query(..., description="Original URL to redirect to"),
    db: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    """
    Track email link click and redirect to original URL.

    This endpoint:
    1. Records the click event in the database
    2. Logs the message ID and clicked URL
    3. Redirects user to the original URL (302 redirect)

    **URL Parameter:**
    - `url`: URL-encoded original URL to redirect to

    **Tracking:**
    - All clicks are recorded (not just first click)
    - Click events are stored with timestamp and full URL
    - Used for analytics and engagement metrics

    **Example:**
    ```
    GET /api/track/click/123e4567-e89b-12d3-a456-426614174000?url=https%3A%2F%2Fexample.com
    → Records click and redirects to https://example.com
    ```

    **Fallback:**
    - If message ID is invalid, redirects to fallback URL
    - If URL parameter is missing, redirects to fallback URL
    - Always returns 302 redirect (never errors)
    """
    try:
        # Decode URL
        decoded_url = unquote(url)

        # Record click (best effort - don't fail if recording fails)
        try:
            await tracking_service.record_click(db, tracking_id, decoded_url)
        except Exception as e:
            logger.error(f"Failed to record click for {tracking_id}: {str(e)}")
            # Continue to redirect anyway

        # Redirect to original URL
        return RedirectResponse(
            url=decoded_url,
            status_code=status.HTTP_302_FOUND,
        )

    except Exception as e:
        logger.error(f"Error in click tracking: {str(e)}")
        # Redirect to fallback URL
        return RedirectResponse(
            url=settings.FALLBACK_REDIRECT_URL,
            status_code=status.HTTP_302_FOUND,
        )


@router.get("/track/open/{tracking_id}")
async def track_open(
    tracking_id: str,
    db: AsyncSession = Depends(get_session),
) -> Response:
    """
    Track email open and return 1x1 transparent GIF.

    This endpoint:
    1. Records the FIRST open event (subsequent opens ignored)
    2. Returns a 1x1 transparent GIF image (43 bytes)
    3. Sets Cache-Control headers to prevent caching

    **Tracking:**
    - Only the FIRST open is recorded (opened_at timestamp)
    - Subsequent opens are ignored (idempotent)
    - Email clients that prefetch images may trigger this

    **Response:**
    - Content-Type: image/gif
    - Cache-Control: no-cache, no-store, must-revalidate
    - 1x1 transparent GIF (invisible to user)

    **Example:**
    ```html
    <img src="https://api.example.com/api/track/open/123e4567-..."
         width="1" height="1" style="display:none" />
    ```

    **Notes:**
    - Some email clients block images by default
    - Open tracking is less reliable than click tracking
    - Always returns 200 OK with GIF (even if recording fails)
    """
    try:
        # Record open (best effort - don't fail if recording fails)
        try:
            await tracking_service.record_open(db, tracking_id)
        except Exception as e:
            logger.error(f"Failed to record open for {tracking_id}: {str(e)}")
            # Continue to return pixel anyway

    except Exception as e:
        logger.error(f"Error in open tracking: {str(e)}")

    # Always return the tracking pixel
    return Response(
        content=TRACKING_PIXEL_GIF,
        media_type="image/gif",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )
