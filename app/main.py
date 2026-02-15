"""FastAPI application factory and configuration."""

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    print(f"Starting SES Email Service in {settings.ENVIRONMENT} mode")
    print(f"Base URL: {settings.APP_BASE_URL}")
    print(f"Database: {settings.DATABASE_URL.split('@')[-1]}")  # Hide credentials
    yield
    # Shutdown
    print("Shutting down SES Email Service")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="SES Email Service",
        description="Production-ready email delivery service using AWS SES",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure based on environment in production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Health check endpoint
    @app.get("/health", tags=["Health"])
    async def health_check() -> dict[str, Any]:
        """Health check endpoint."""
        return {
            "status": "healthy",
            "service": "ses-email-service",
            "version": "0.1.0",
            "environment": settings.ENVIRONMENT,
        }

    # Root endpoint
    @app.get("/", tags=["Root"])
    async def root() -> dict[str, str]:
        """Root endpoint with API information."""
        return {
            "message": "SES Email Service API",
            "docs": "/docs",
            "health": "/health",
        }

    # Mount routes
    from app.routes import emails, tracking, webhooks

    app.include_router(emails.router, prefix="/api", tags=["Emails"])
    app.include_router(webhooks.router, prefix="/api", tags=["Webhooks"])
    app.include_router(tracking.router, prefix="/api", tags=["Tracking"])

    # Additional routes (will be added in later phases)
    # from app.routes import suppressions, domains, unsubscribe, dashboard
    # app.include_router(suppressions.router, prefix="/api", tags=["Suppressions"])
    # app.include_router(domains.router, prefix="/api", tags=["Domains"])
    # app.include_router(unsubscribe.router, tags=["Unsubscribe"])
    # app.include_router(dashboard.router, tags=["Dashboard"])

    return app


# Create application instance
app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.ENVIRONMENT == "development",
        log_level=settings.LOG_LEVEL.lower(),
    )
