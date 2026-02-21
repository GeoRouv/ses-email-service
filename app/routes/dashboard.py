"""Dashboard routes for admin UI."""

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import datetime, timezone

from app.database import get_session
from app.services import dashboard_service, domain_service, suppression_service

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_index(
    request: Request,
    days: int = Query(7, ge=1, le=90),
    db: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    """Render main dashboard with metrics and chart."""
    metrics = await dashboard_service.get_dashboard_metrics(db, days=days)
    chart_data = await dashboard_service.get_daily_volume(db, days=days)

    return templates.TemplateResponse(
        "dashboard/index.html",
        {
            "request": request,
            "active_page": "dashboard",
            "metrics": metrics,
            "chart_data": chart_data,
        },
    )


@router.get("/api/dashboard/metrics")
async def dashboard_metrics_api(
    days: int = Query(7, ge=1, le=90),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """
    Get dashboard metrics as JSON.

    **Query Parameters:**
    - `days`: Number of days to look back (1-90, default: 7)

    **Response:**
    ```json
    {
      "total_sent": 150,
      "delivered": 140,
      "bounced": 5,
      "opened": 80,
      "deferred": 3,
      "complained": 2,
      "clicked_messages": 45,
      "delivery_rate": 93.3,
      "open_rate": 57.1,
      "click_rate": 32.1,
      "bounce_rate": 3.3,
      "days": 7
    }
    ```
    """
    return await dashboard_service.get_dashboard_metrics(db, days=days)


@router.get("/dashboard/activity", response_class=HTMLResponse)
async def activity_list(
    request: Request,
    page: int = Query(1, ge=1),
    status: str | None = Query(None),
    db: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    """Render activity list with paginated messages."""
    activity = await dashboard_service.get_activity_list(
        db,
        page=page,
        per_page=25,
        status_filter=status,
    )

    context = {
        "request": request,
        "active_page": "activity",
        "activity": activity,
    }

    # HTMX partial response — return only the table
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse("partials/activity_table.html", context)

    return templates.TemplateResponse("dashboard/activity.html", context)


@router.get("/dashboard/activity/{message_id}", response_class=HTMLResponse)
async def message_detail(
    request: Request,
    message_id: UUID,
    db: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    """Render message detail page with events and clicks."""
    detail = await dashboard_service.get_message_detail(db, message_id)

    if not detail:
        return HTMLResponse(
            content="<h1>Message not found</h1>",
            status_code=404,
        )

    return templates.TemplateResponse(
        "dashboard/message_detail.html",
        {
            "request": request,
            "active_page": "activity",
            "message": detail["message"],
            "events": detail["events"],
            "click_events": detail["click_events"],
        },
    )


@router.get("/dashboard/suppressions", response_class=HTMLResponse)
async def suppressions_view(
    request: Request,
    page: int = Query(1, ge=1),
    db: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    """Render suppression list management page."""
    suppressions, total = await suppression_service.get_suppressions(
        db,
        page=page,
        page_size=25,
    )

    per_page = 25
    pages = max(1, -(-total // per_page))

    context = {
        "request": request,
        "active_page": "suppressions",
        "suppressions": suppressions,
        "total": total,
        "page": page,
        "pages": pages,
        "per_page": per_page,
    }

    # HTMX partial response
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse("partials/suppression_table.html", context)

    return templates.TemplateResponse("dashboard/suppressions.html", context)


@router.get("/dashboard/domains", response_class=HTMLResponse)
async def domains_view(
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    """Render domain management page."""
    domains, total = await domain_service.list_domains(db)

    return templates.TemplateResponse(
        "dashboard/domains.html",
        {
            "request": request,
            "active_page": "domains",
            "domains": domains,
            "total": total,
        },
    )


@router.get("/dashboard/deferred", response_class=HTMLResponse)
async def deferred_view(
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    """Render deferred emails view."""
    messages, total = await dashboard_service.get_deferred_messages(db)

    return templates.TemplateResponse(
        "dashboard/deferred.html",
        {
            "request": request,
            "active_page": "deferred",
            "messages": messages,
            "total": total,
            "now": datetime.now(timezone.utc),
        },
    )
