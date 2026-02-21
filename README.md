# SES Email Service

Production-ready email delivery service built on AWS SES with click/open tracking, suppression list management, domain verification, and a real-time analytics dashboard.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         FastAPI Application                         │
│                                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────────────┐  │
│  │  Routes   │  │ Services │  │  Models  │  │   Utils           │  │
│  │ (HTTP)    │→ │ (Logic)  │→ │  (ORM)   │  │ - Email validator │  │
│  │          │  │          │  │          │  │ - HTML processor  │  │
│  │ emails   │  │ email    │  │ message  │  │ - SNS validator   │  │
│  │ webhooks │  │ webhook  │  │ event    │  │ - Email masking   │  │
│  │ tracking │  │ tracking │  │ click    │  └───────────────────┘  │
│  │ suppress │  │ suppress │  │ suppress │                         │
│  │ domains  │  │ domain   │  │ domain   │                         │
│  │ unsub    │  │ unsub    │  │          │                         │
│  │ dashboard│  │ dashboard│  │          │                         │
│  └──────────┘  └──────────┘  └──────────┘                         │
│                      │              │                               │
│                      ▼              ▼                               │
│               ┌────────────┐ ┌────────────┐                        │
│               │ SES Client │ │ PostgreSQL │                        │
│               │ (aioboto3) │ │ (asyncpg)  │                        │
│               └──────┬─────┘ └────────────┘                        │
└──────────────────────┼─────────────────────────────────────────────┘
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
    ┌──────────┐ ┌──────────┐ ┌──────────┐
    │ AWS SES  │ │ AWS SNS  │ │ Recipient│
    │ (send)   │ │ (events) │ │ (email)  │
    └──────────┘ └────┬─────┘ └──────────┘
                      │
                      ▼
               POST /api/webhooks/ses
               (delivery, bounce, complaint, delay, reject)
```

**Layer responsibilities:**
- **Routes** — HTTP concerns only: parse request, call service, return response
- **Services** — All business logic: validation, state transitions, DB operations
- **Models** — SQLAlchemy ORM classes, no business logic
- **Schemas** — Pydantic request/response validation
- **Utils** — Pure functions: email validation, HTML processing, SNS signature verification

## Tech Stack

| Layer | Choice | Why |
|-------|--------|-----|
| Framework | FastAPI (async) | Auto-generated Swagger docs, Pydantic validation, native async |
| Database | PostgreSQL 16 | JSONB for raw payloads, aggregation for dashboard metrics |
| ORM | SQLAlchemy 2.0 (async) | Mature async support, Alembic migrations |
| AWS SDK | aioboto3 | Async SES/SNS calls, no blocking |
| Templates | Jinja2 + Tailwind CSS (CDN) | Server-rendered dashboard, no build step |
| Charts | Chart.js (CDN) | Time series for daily email volume |
| Interactivity | HTMX (CDN) | Pagination, modals, inline updates without React |
| Auth tokens | PyJWT (HMAC-SHA256) | Signed unsubscribe tokens with 30-day expiry |
| HTML parsing | BeautifulSoup4 | URL rewriting for click tracking, pixel injection |
| Testing | pytest + pytest-asyncio | 168 tests, 80% coverage |

## Features

- **Email Sending** — Send HTML emails via SES with validation, suppression checks, and domain verification
- **Click & Open Tracking** — Automatic URL rewriting and tracking pixel injection in outgoing emails
- **Webhook Processing** — SNS signature-verified webhook handler for delivery, bounce, complaint, delay, and reject events
- **Suppression List** — Auto-suppresses on hard bounces and complaints; manual add/remove via API
- **Domain Verification** — Initiate SES domain verification, view DNS records, check status
- **Unsubscribe Flow** — JWT-signed unsubscribe links with confirmation page and `List-Unsubscribe` header
- **Dashboard** — Real-time metrics, daily volume chart, activity log, message detail, suppression and domain management
- **Safety Guards** — Recipient domain allowlist, sender domain verification, email format validation

## Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL 16+
- AWS account with SES access

### Option 1: Docker Compose (recommended)

```bash
# Clone and configure
git clone <repo-url> && cd ses-email-service
cp .env.example .env
# Edit .env with your AWS credentials

# Start everything
docker compose up -d

# App runs at http://localhost:8000
# Dashboard at http://localhost:8000/dashboard
# API docs at http://localhost:8000/docs
```

### Option 2: Manual Setup

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Create database
createdb ses_email

# Configure
cp .env.example .env
# Edit .env with your credentials and DATABASE_URL

# Run migrations
alembic upgrade head

# Start server
uvicorn app.main:app --reload --port 8000
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes | `postgresql+asyncpg://postgres:postgres@localhost:5432/ses_email` | PostgreSQL connection string |
| `AWS_ACCESS_KEY_ID` | Yes | — | AWS IAM access key |
| `AWS_SECRET_ACCESS_KEY` | Yes | — | AWS IAM secret key |
| `AWS_REGION` | No | `us-east-1` | AWS region |
| `SES_CONFIGURATION_SET` | No | `ses-assessment-tracking` | SES config set for event routing |
| `SNS_TOPIC_ARN` | No | (pre-configured) | SNS topic for SES events |
| `VERIFIED_DOMAIN` | No | `candidate-test.kubbly.com` | Pre-verified sending domain |
| `APP_BASE_URL` | No | `http://localhost:8000` | Base URL for tracking links |
| `UNSUBSCRIBE_SECRET` | No | `change-me-in-production` | JWT signing secret |
| `FALLBACK_REDIRECT_URL` | No | `https://example.com` | Redirect for invalid tracking IDs |
| `ALLOWED_EMAIL_DOMAINS` | No | `kubbly.com` | Comma-separated recipient domain allowlist |
| `EMAIL_RATE_LIMIT_PER_HOUR` | No | `15` | Hourly send rate limit |
| `LOG_LEVEL` | No | `INFO` | Logging level |
| `ENVIRONMENT` | No | `development` | Environment name |

## API Endpoints

### Email Sending

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/emails/send` | Send an email |

### Webhooks

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/webhooks/ses` | Receive SNS/SES event notifications |

### Tracking

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/track/click/{id}` | Track link click, redirect to original URL |
| `GET` | `/api/track/open/{id}` | Track email open, return 1x1 GIF |

### Suppression List

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/suppressions` | List suppressions (paginated, filterable by reason) |
| `POST` | `/api/suppressions` | Add email to suppression list |
| `DELETE` | `/api/suppressions/{email}` | Remove email from suppression list |
| `GET` | `/api/suppressions/check/{email}` | Check if email is suppressed |

### Domain Verification

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/domains/verify` | Initiate domain verification |
| `GET` | `/api/domains` | List all domains |
| `GET` | `/api/domains/{domain}/records` | Get required DNS records |
| `GET` | `/api/domains/{domain}/status` | Check verification status |
| `DELETE` | `/api/domains/{domain}` | Remove domain from local DB |

### Dashboard

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/dashboard` | Dashboard overview (HTML) |
| `GET` | `/api/dashboard/metrics` | Metrics data (JSON) |
| `GET` | `/dashboard/activity` | Activity log (HTML) |
| `GET` | `/dashboard/activity/{id}` | Message detail (HTML) |
| `GET` | `/dashboard/suppressions` | Suppression management (HTML) |
| `GET` | `/dashboard/domains` | Domain management (HTML) |
| `GET` | `/dashboard/deferred` | Deferred emails (HTML) |

### Unsubscribe

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/unsubscribe/{token}` | Unsubscribe confirmation page |
| `POST` | `/unsubscribe/{token}` | Process unsubscribe |

### Utility

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/docs` | Swagger UI |

## Email Flow

```
1. POST /api/emails/send
   ├── Validate email format (RFC 5322)
   ├── Check recipient domain allowlist
   ├── Check suppression list
   ├── Verify sender domain (SES)
   ├── Rewrite HTML URLs for click tracking
   ├── Inject unsubscribe link
   ├── Inject tracking pixel
   ├── Send via SES (with List-Unsubscribe header)
   └── Save message record (status: "sent")

2. SES delivers email → triggers SNS event
   ├── POST /api/webhooks/ses
   ├── Verify SNS signature
   ├── Parse SES event from SNS envelope
   └── Update message status:
       ├── Delivery  → "delivered"
       ├── Bounce    → "bounced" (+ auto-suppress on hard bounce)
       ├── Complaint → "complained" (+ auto-suppress)
       ├── Delay     → "deferred"
       └── Reject    → "rejected"

3. Recipient interactions
   ├── Opens email → GET /api/track/open/{id} → records first open
   ├── Clicks link → GET /api/track/click/{id} → records click, redirects
   └── Unsubscribes → GET/POST /unsubscribe/{token} → adds to suppression
```

## Design Decisions

1. **Separate click_events table** — Click events come from our tracking endpoint, not SES webhooks. Different data shape (URL, no raw SES payload). Keeping them separate avoids polluting the SES event stream.

2. **opened_at on messages table** — Spec requires tracking first open only. A nullable timestamp is simpler than a separate table.

3. **Domain delete is local-only** — `DELETE /api/domains/{domain}` removes from our DB but doesn't call SES `DeleteIdentity`. This is safer — SES state is preserved in case of accidental deletion.

4. **Suppression check returns simple response** — The spec's suppression check response schema included pagination fields (copy-paste from list endpoint). We return `{ suppressed, email, reason, created_at }` instead.

5. **Unsubscribe link is not click-tracked** — The unsubscribe URL in the email body is injected after URL rewriting, so it goes directly to the unsubscribe page without passing through click tracking.

6. **Webhooks always return 200** — Even on processing errors, the webhook endpoint returns success to prevent SNS from retrying indefinitely.

7. **Rates use total_sent as denominator** — Open rate and click rate divide by total sent (not delivered) so metrics display correctly even before delivery webhooks are processed.

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov-report=term-missing

# Run specific test file
pytest tests/test_email_service.py -v

# Run a single test
pytest tests/test_sns_validator.py::TestVerifySnSSignature::test_valid_signature_returns_true -v
```

**Coverage: 168 tests, 80%**

| Module | Coverage |
|--------|----------|
| Services | 93-100% |
| Utils | 86-100% |
| Schemas | 86-96% |
| Models | 93-96% |
| Routes | 21-89% (thin HTTP wrappers over tested services) |

Tests require a local PostgreSQL database named `ses_email_test`:

```bash
createdb ses_email_test
```

## Database Schema

5 tables: `messages`, `events`, `click_events`, `suppressions`, `domains`

```
messages (1) ──→ (N) events        # SES delivery/bounce/complaint/delay/reject
messages (1) ──→ (N) click_events  # Link click tracking
suppressions                       # Bounced/complained/unsubscribed emails
domains                            # Verified sending domains
```

Migrations are managed with Alembic:

```bash
alembic upgrade head      # Apply all migrations
alembic downgrade -1      # Rollback one migration
```

## Project Structure

```
ses-email-service/
├── app/
│   ├── main.py              # FastAPI app factory
│   ├── config.py            # Pydantic settings
│   ├── database.py          # Async SQLAlchemy engine
│   ├── models/              # ORM models
│   ├── schemas/             # Pydantic request/response
│   ├── services/            # Business logic
│   ├── routes/              # HTTP route handlers
│   ├── utils/               # Pure utility functions
│   └── templates/           # Jinja2 templates (dashboard, unsubscribe)
├── tests/                   # 168 tests (80% coverage)
├── alembic/                 # Database migrations
├── docker-compose.yml       # Postgres + app
├── Dockerfile               # Production image
├── requirements.txt         # Python dependencies
└── pyproject.toml           # Project metadata
```
