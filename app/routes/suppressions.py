"""Suppression list API routes."""

import logging
from math import ceil

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.schemas.suppression import (
    AddSuppressionRequest,
    SuppressionAddResponse,
    SuppressionCheckResponse,
    SuppressionListResponse,
)
from app.services import suppression_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/suppressions", response_model=SuppressionListResponse)
async def list_suppressions(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(25, ge=1, le=100, description="Items per page (max 100)"),
    reason: str | None = Query(None, description="Filter by suppression reason"),
    db: AsyncSession = Depends(get_session),
) -> SuppressionListResponse:
    """
    Get paginated suppression list with optional filtering.

    Returns all suppressed email addresses with their suppression reason
    and timestamp. Useful for reviewing and managing the suppression list.

    **Query Parameters:**
    - `page`: Page number (1-indexed, default: 1)
    - `page_size`: Items per page (1-100, default: 25)
    - `reason`: Optional filter by suppression reason (hard_bounce, complaint, unsubscribe, manual)

    **Response:**
    - Paginated list of suppressed emails with metadata
    - Total count and page information

    **Example:**
    ```
    GET /api/suppressions?page=1&page_size=25&reason=hard_bounce
    ```

    **Use Cases:**
    - Review suppressed emails before a campaign
    - Export suppression list for compliance
    - Monitor auto-suppressions from bounces/complaints
    """
    suppressions, total = await suppression_service.get_suppressions(
        db=db,
        page=page,
        page_size=page_size,
        reason=reason,
    )

    total_pages = ceil(total / page_size) if total > 0 else 0

    return SuppressionListResponse(
        items=suppressions,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.post(
    "/suppressions",
    response_model=SuppressionAddResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_suppression(
    request: AddSuppressionRequest,
    db: AsyncSession = Depends(get_session),
) -> SuppressionAddResponse:
    """
    Add email address to suppression list.

    Prevents future emails from being sent to this address. The email
    is validated and stored with a reason for suppression.

    **Request Body:**
    ```json
    {
      "email": "user@example.com",
      "reason": "manual"
    }
    ```

    **Valid Reasons:**
    - `hard_bounce`: Email permanently bounced (invalid/non-existent)
    - `complaint`: User marked email as spam
    - `unsubscribe`: User clicked unsubscribe link
    - `manual`: Manually added by administrator

    **Response:**
    - 201 Created: Email successfully added to suppression list
    - 400 Bad Request: Invalid email format or reason
    - 409 Conflict: Email already on suppression list

    **Automatic Suppression:**
    - Hard bounces are auto-added via SES webhooks
    - Complaints (spam reports) are auto-added via SES webhooks
    - Unsubscribes are auto-added via unsubscribe links
    - Manual adds are for admin/compliance purposes

    **Example:**
    ```bash
    curl -X POST https://api.example.com/api/suppressions \\
      -H "Content-Type: application/json" \\
      -d '{"email": "user@example.com", "reason": "manual"}'
    ```
    """
    suppression = await suppression_service.add_suppression(db, request)

    return SuppressionAddResponse(
        success=True,
        email=suppression.email,
        reason=suppression.reason,
        created_at=suppression.created_at,
    )


@router.delete("/suppressions/{email}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_suppression(
    email: str,
    db: AsyncSession = Depends(get_session),
) -> Response:
    """
    Remove email address from suppression list.

    Allows emails to be sent to this address again. Use with caution -
    only remove emails if you're certain it's safe to send to them.

    **Path Parameter:**
    - `email`: Email address to remove (URL-encoded)

    **Response:**
    - 204 No Content: Email successfully removed
    - 404 Not Found: Email not on suppression list

    **Warning:**
    Removing an email that hard bounced or complained will allow future
    sends, but SES may penalize your account if bounces/complaints recur.
    Only remove suppressions when:
    - Email address was fixed by recipient
    - Manual suppression added in error
    - Complaint was resolved with recipient

    **Example:**
    ```bash
    curl -X DELETE https://api.example.com/api/suppressions/user@example.com
    ```
    """
    removed = await suppression_service.remove_suppression(db, email)

    if not removed:
        return Response(status_code=status.HTTP_404_NOT_FOUND)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/suppressions/check/{email}", response_model=SuppressionCheckResponse)
async def check_suppression(
    email: str,
    db: AsyncSession = Depends(get_session),
) -> SuppressionCheckResponse:
    """
    Check if email address is suppressed.

    Returns suppression status with reason and timestamp if suppressed.
    Useful for pre-send validation and UI feedback.

    **Path Parameter:**
    - `email`: Email address to check (URL-encoded)

    **Response:**
    ```json
    {
      "email": "user@example.com",
      "suppressed": true,
      "reason": "hard_bounce",
      "created_at": "2024-01-15T10:30:00Z"
    }
    ```

    **Use Cases:**
    - Pre-send validation in bulk email tools
    - Check suppression status in admin UI
    - API integration for external systems
    - Compliance and reporting

    **Example:**
    ```bash
    curl https://api.example.com/api/suppressions/check/user@example.com
    ```

    **Integration:**
    The email send endpoint automatically checks suppressions and rejects
    suppressed recipients with error code `EMAIL_SUPPRESSED`.
    """
    return await suppression_service.check_suppression(db, email)
