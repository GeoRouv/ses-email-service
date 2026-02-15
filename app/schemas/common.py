"""Common Pydantic schemas used across the application."""

from typing import Any

from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict


class ErrorDetail(BaseModel):
    """Error detail structure."""

    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    """Standard error response format."""

    success: bool = False
    error: ErrorDetail


class SuccessResponse(BaseModel):
    """Standard success response format."""

    success: bool = True
    data: dict[str, Any] | None = None


def raise_api_error(
    code: str,
    message: str,
    status_code: int = status.HTTP_400_BAD_REQUEST,
    details: dict[str, Any] | None = None,
) -> None:
    """
    Raise an HTTPException with standardized error format.

    Args:
        code: Machine-readable error code (e.g., "INVALID_EMAIL")
        message: Human-readable error message
        status_code: HTTP status code (default: 400)
        details: Optional additional error context
    """
    raise HTTPException(
        status_code=status_code,
        detail={
            "success": False,
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
            },
        },
    )


class PaginationParams(BaseModel):
    """Pagination parameters for list endpoints."""

    model_config = ConfigDict(from_attributes=True)

    page: int = 1
    page_size: int = 25

    @property
    def offset(self) -> int:
        """Calculate offset from page and page_size."""
        return (self.page - 1) * self.page_size


class PaginatedResponse(BaseModel):
    """Paginated response wrapper."""

    items: list[Any]
    total: int
    page: int
    page_size: int
    total_pages: int

    @classmethod
    def create(
        cls,
        items: list[Any],
        total: int,
        page: int,
        page_size: int,
    ) -> "PaginatedResponse":
        """Create a paginated response."""
        total_pages = (total + page_size - 1) // page_size if total > 0 else 0
        return cls(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )
