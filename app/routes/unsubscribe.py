"""Unsubscribe routes for email opt-out flow."""

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.services import unsubscribe_service
from app.utils.email_masking import mask_email

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/unsubscribe/{token}", response_class=HTMLResponse)
async def unsubscribe_confirm(
    request: Request,
    token: str,
) -> HTMLResponse:
    """
    Display unsubscribe confirmation page.

    Validates the JWT token and shows a confirmation page with the masked
    email address. The user must click "Confirm Unsubscribe" to complete
    the process.

    **Path Parameter:**
    - `token`: Signed JWT token containing email and message_id

    **Token Payload:**
    ```json
    {
      "email": "user@example.com",
      "message_id": "uuid-string",
      "iat": 1705312200,
      "exp": 1707904200
    }
    ```

    **Pages:**
    - Valid token: Shows confirmation page with masked email and confirm button
    - Invalid/expired token: Shows error page explaining the issue

    **Security:**
    - Tokens are signed with HMAC-SHA256
    - Tokens expire after 30 days
    - Email is masked on the page (j***@example.com)
    """
    # Validate token
    payload = unsubscribe_service.validate_unsubscribe_token(token)

    if not payload:
        return templates.TemplateResponse(
            "unsubscribe/error.html",
            {
                "request": request,
                "error_message": "This unsubscribe link is invalid or has expired.",
            },
        )

    email = payload["email"]
    masked = mask_email(email)

    return templates.TemplateResponse(
        "unsubscribe/confirm.html",
        {
            "request": request,
            "masked_email": masked,
            "token": token,
        },
    )


@router.post("/unsubscribe/{token}", response_class=HTMLResponse)
async def unsubscribe_process(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    """
    Process unsubscribe request.

    Validates the JWT token, adds the email to the suppression list with
    reason "unsubscribe", and shows a success page.

    **Path Parameter:**
    - `token`: Signed JWT token containing email and message_id

    **Behavior:**
    - Valid token, not yet unsubscribed: Adds to suppression list, shows success
    - Valid token, already unsubscribed: Shows success (idempotent, double-submit prevention)
    - Invalid/expired token: Shows error page

    **Suppression:**
    - Email is added with reason "unsubscribe"
    - Future sends to this email will be rejected with EMAIL_SUPPRESSED error
    - The email can be re-enabled via DELETE /api/suppressions/{email}
    """
    # Validate token
    payload = unsubscribe_service.validate_unsubscribe_token(token)

    if not payload:
        return templates.TemplateResponse(
            "unsubscribe/error.html",
            {
                "request": request,
                "error_message": "This unsubscribe link is invalid or has expired.",
            },
        )

    email = payload["email"]
    masked = mask_email(email)

    # Process unsubscribe (idempotent)
    try:
        await unsubscribe_service.process_unsubscribe(db, email)
    except Exception as e:
        logger.error(f"Failed to process unsubscribe for {email}: {e}")
        return templates.TemplateResponse(
            "unsubscribe/error.html",
            {
                "request": request,
                "error_message": "Something went wrong. Please try again later.",
            },
        )

    return templates.TemplateResponse(
        "unsubscribe/success.html",
        {
            "request": request,
            "masked_email": masked,
        },
    )
