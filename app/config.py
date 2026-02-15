"""Application configuration using pydantic-settings."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/ses_email",
        description="Async PostgreSQL connection string",
    )

    # AWS Credentials
    AWS_ACCESS_KEY_ID: str = Field(..., description="AWS access key ID")
    AWS_SECRET_ACCESS_KEY: str = Field(..., description="AWS secret access key")
    AWS_REGION: str = Field(default="us-east-1", description="AWS region")

    # SES Configuration
    SES_CONFIGURATION_SET: str = Field(
        default="ses-assessment-tracking",
        description="SES configuration set name for tracking",
    )
    SNS_TOPIC_ARN: str = Field(
        default="arn:aws:sns:us-east-1:148761646433:ses-assessment-events",
        description="SNS topic ARN for SES events",
    )
    VERIFIED_DOMAIN: str = Field(
        default="candidate-test.kubbly.com",
        description="Pre-verified sending domain",
    )

    # Application Settings
    APP_BASE_URL: str = Field(
        default="http://localhost:8000",
        description="Base URL for tracking links and unsubscribe URLs",
    )
    UNSUBSCRIBE_SECRET: str = Field(
        default="change-me-in-production",
        description="Secret key for JWT token signing (unsubscribe tokens)",
    )
    FALLBACK_REDIRECT_URL: str = Field(
        default="https://example.com",
        description="Redirect URL for invalid tracking IDs",
    )

    # Safety & Rate Limiting
    ALLOWED_EMAIL_DOMAINS: str = Field(
        default="kubbly.com",
        description="Comma-separated list of allowed recipient domains",
    )
    EMAIL_RATE_LIMIT_PER_HOUR: int = Field(
        default=15,
        description="Maximum emails per hour (for sandbox testing)",
    )

    # Logging
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")

    # Environment
    ENVIRONMENT: str = Field(default="development", description="Environment name")

    @property
    def allowed_domains_list(self) -> list[str]:
        """Parse allowed email domains as a list."""
        return [d.strip() for d in self.ALLOWED_EMAIL_DOMAINS.split(",") if d.strip()]


# Global settings instance
settings = Settings()
