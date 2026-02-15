"""Webhook-related Pydantic schemas."""

from typing import Any

from pydantic import BaseModel, Field


class SNSMessage(BaseModel):
    """SNS message envelope schema."""

    Type: str = Field(..., description="Message type (Notification, SubscriptionConfirmation, etc.)")
    MessageId: str = Field(..., description="SNS message ID")
    TopicArn: str | None = Field(None, description="SNS topic ARN")
    Subject: str | None = Field(None, description="Message subject (optional)")
    Message: str = Field(..., description="JSON-stringified message content")
    Timestamp: str = Field(..., description="Message timestamp")
    SignatureVersion: str = Field(..., description="Signature version")
    Signature: str = Field(..., description="Message signature")
    SigningCertURL: str = Field(..., description="URL to signing certificate")
    UnsubscribeURL: str | None = Field(None, description="Unsubscribe URL (optional)")
    Token: str | None = Field(None, description="Subscription token (for confirmations)")
    SubscribeURL: str | None = Field(None, description="Subscribe URL (for confirmations)")


class WebhookResponse(BaseModel):
    """Standard webhook response."""

    success: bool = True
    message: str = "Webhook processed successfully"
    event_type: str | None = None
    message_id: str | None = None


class SESEventMail(BaseModel):
    """Common mail object in SES events."""

    messageId: str
    timestamp: str
    source: str
    destination: list[str]
    tags: dict[str, list[str]] | None = None


class SESDeliveryEvent(BaseModel):
    """SES Delivery event payload."""

    eventType: str = "Delivery"
    mail: dict[str, Any]
    delivery: dict[str, Any]


class SESBounceEvent(BaseModel):
    """SES Bounce event payload."""

    eventType: str = "Bounce"
    mail: dict[str, Any]
    bounce: dict[str, Any]


class SESComplaintEvent(BaseModel):
    """SES Complaint event payload."""

    eventType: str = "Complaint"
    mail: dict[str, Any]
    complaint: dict[str, Any]


class SESDeliveryDelayEvent(BaseModel):
    """SES DeliveryDelay event payload."""

    eventType: str = "DeliveryDelay"
    mail: dict[str, Any]
    deliveryDelay: dict[str, Any]


class SESRejectEvent(BaseModel):
    """SES Reject event payload."""

    eventType: str = "Reject"
    mail: dict[str, Any]
    reject: dict[str, Any]
