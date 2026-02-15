# PLAN.md — SES Email Delivery Service

## Spec Analysis & Critical Observations

### Evaluation Weights (drive all prioritization)
| Criteria | Weight | Implication |
|----------|--------|-------------|
| Core functionality | 35% | Email sending, webhooks, tracking MUST work flawlessly |
| Code quality | 25% | Clean architecture, type hints, error handling, separation of concerns |
| Dashboard | 20% | Must show real data, be usable, no broken UI |
| API design | 10% | Consistent error format, proper status codes, RESTful |
| Documentation | 10% | README must let someone clone and run it |

### Spec Bugs & Ambiguities (document in README)
1. **Suppression check endpoint** (Section 5): Response schema is copy-pasted from the list endpoint — includes pagination for a single-record lookup. We'll return a simple `{ suppressed: bool, email, reason, createdAt }` instead and document why.
2. **Unsubscribe POST** (Section 6): Requirements list is duplicated from the GET (mentions "display confirmation page" and "confirm button" on the POST). POST should process the unsubscribe and show a success/already-unsubscribed page.
3. **Click tracking URL structure**: Spec says `GET /api/track/click/:trackingId?url=...` but doesn't specify how trackingId maps to a message. We'll use the message ID as trackingId since it's already unique.
4. **Domain delete** (Section 7.5): Spec says "remove from local database" but doesn't mention calling SES `DeleteIdentity`. We'll only delete locally (keeps SES state intact for safety) and document this decision.
5. **Rate limiting**: The credentials template mentions app-level rate limits (200/day, 1/sec) but the spec doesn't list it as a requirement. We'll implement a simple in-memory rate limiter as a bonus — shows production thinking.

### AWS Resources Already Provided
- **Access keys**: Provided in credentials template
- **SNS Topic**: `arn:aws:sns:us-east-1:148761646433:ses-assessment-events`
- **Configuration Set**: `ses-assessment-tracking`
- **Verified Domain**: `candidate-test.kubbly.com`
- This means we can send from `*@candidate-test.kubbly.com` immediately

---

## Tech Stack (Final)

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Framework | FastAPI (async) | Auto Swagger docs, Pydantic validation, async boto3 |
| Database | PostgreSQL | Aggregation queries for dashboard, JSONB for raw payloads |
| ORM | SQLAlchemy 2.0 (async) + Alembic | Async support, mature migrations |
| AWS SDK | boto3 + aioboto3 | Async SES/SNS calls to avoid blocking |
| Templates | Jinja2 | Built into FastAPI, server-rendered dashboard |
| CSS | Tailwind CSS (CDN) | Fast styling, no build step |
| Charts | Chart.js (CDN) | Simple, good-looking time series |
| Interactivity | HTMX (CDN) | Modals, pagination, inline updates without React |
| Auth tokens | PyJWT + HMAC | Unsubscribe token signing |
| HTML parsing | BeautifulSoup4 | URL rewriting for click tracking, pixel injection |
| Testing | pytest + pytest-asyncio + httpx | Async test support, TestClient |
| Deployment | Railway (or Render) | Free tier with managed Postgres |

### Why NOT certain choices
- **No Celery/Redis**: Overkill for this scope. SES retries are handled by AWS. Exponential backoff on send is simple with tenacity.
- **No React**: Jinja + HTMX gives us interactive modals, pagination, and partial page updates with zero JS build step.
- **No alembic autogenerate initially**: We'll write explicit migrations — cleaner and more predictable.

---

## Database Schema

### Core Tables

```
┌─────────────────────────────────────────┐
│ messages                                │
├─────────────────────────────────────────┤
│ id              UUID (PK)               │
│ ses_message_id  VARCHAR (unique, index) │
│ to_email        VARCHAR (index)         │
│ from_email      VARCHAR                 │
│ from_name       VARCHAR (nullable)      │
│ subject         VARCHAR                 │
│ html_content    TEXT                     │
│ text_content    TEXT (nullable)          │
│ status          VARCHAR (index)         │ ← sent|delivered|bounced|deferred|rejected|complained
│ message_metadata JSONB (nullable)       │ ← renamed from 'metadata' (SQLAlchemy reserved name)
│ opened_at       TIMESTAMP (nullable)    │
│ first_deferred_at TIMESTAMP (nullable)  │
│ created_at      TIMESTAMP (index)       │ ← for daily aggregation
│ updated_at      TIMESTAMP               │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│ events                                  │
├─────────────────────────────────────────┤
│ id              UUID (PK)               │
│ message_id      UUID (FK → messages)    │
│ event_type      VARCHAR (index)         │ ← delivery|bounce|complaint|delay|reject
│ bounce_type     VARCHAR (nullable)      │ ← hard|soft (only for bounces)
│ bounce_reason   TEXT (nullable)          │
│ delay_type      VARCHAR (nullable)      │
│ delay_reason    TEXT (nullable)          │
│ raw_payload     JSONB                   │
│ timestamp       TIMESTAMP               │
│ created_at      TIMESTAMP               │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│ suppressions                            │
├─────────────────────────────────────────┤
│ id              UUID (PK)               │
│ email           VARCHAR (unique, index) │ ← fast lookup is critical
│ reason          VARCHAR                 │ ← hard_bounce|complaint|unsubscribe|manual
│ created_at      TIMESTAMP               │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│ domains                                 │
├─────────────────────────────────────────┤
│ id              UUID (PK)               │
│ domain          VARCHAR (unique)        │
│ verification_status VARCHAR             │ ← Pending|Success|Failed|TemporaryFailure
│ dkim_status     VARCHAR                 │
│ verification_token VARCHAR              │
│ dkim_tokens     JSONB                   │ ← array of 3 tokens
│ verified_at     TIMESTAMP (nullable)    │
│ created_at      TIMESTAMP               │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│ click_events                            │
├─────────────────────────────────────────┤
│ id              UUID (PK)               │
│ message_id      UUID (FK → messages)    │
│ url             TEXT                     │
│ clicked_at      TIMESTAMP               │
└─────────────────────────────────────────┘
```

### Key Indexes
- `messages.ses_message_id` — webhook correlation (UNIQUE)
- `messages.status` — dashboard filtering
- `messages.created_at` — daily aggregation, activity list ordering
- `messages.to_email` — suppression check join
- `suppressions.email` — UNIQUE, fast send-time lookup
- `events.message_id` — event history per message

### Why separate click_events (not in events table)
Click events come from our own tracking endpoint, not from SES webhooks. They have different data (URL, no raw SES payload). Keeping them separate avoids polluting the SES event stream and makes click aggregation queries cleaner.

### Why opened_at lives on messages (not a separate table)
Spec says "track first open only." A nullable timestamp on the messages table is the simplest way — one UPDATE, one column check. No extra table needed.

---

## Project Structure

```
ses-email-service/
├── alembic/                    # Database migrations
│   ├── versions/
│   └── env.py
├── alembic.ini
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app factory, mount routes
│   ├── config.py               # Settings from env vars (pydantic-settings)
│   ├── database.py             # SQLAlchemy async engine, session
│   ├── models/                 # SQLAlchemy ORM models
│   │   ├── __init__.py
│   │   ├── message.py
│   │   ├── event.py
│   │   ├── suppression.py
│   │   ├── domain.py
│   │   └── click_event.py
│   ├── schemas/                # Pydantic request/response schemas
│   │   ├── __init__.py
│   │   ├── email.py
│   │   ├── webhook.py
│   │   ├── suppression.py
│   │   ├── domain.py
│   │   └── common.py           # ErrorResponse, PaginationParams
│   ├── services/               # Business logic (no HTTP concerns)
│   │   ├── __init__.py
│   │   ├── email_service.py    # Send logic, suppression check, retry
│   │   ├── webhook_service.py  # SNS parsing, signature validation, event processing
│   │   ├── tracking_service.py # Click/open tracking, URL rewriting, pixel injection
│   │   ├── suppression_service.py
│   │   ├── domain_service.py   # SES domain verification
│   │   ├── unsubscribe_service.py # Token generation/validation
│   │   └── ses_client.py       # boto3/aioboto3 wrapper
│   ├── routes/                 # FastAPI routers (thin — delegate to services)
│   │   ├── __init__.py
│   │   ├── emails.py           # POST /api/emails/send
│   │   ├── webhooks.py         # POST /api/webhooks/ses
│   │   ├── tracking.py         # GET /api/track/click/:id, /api/track/open/:id
│   │   ├── suppressions.py     # CRUD /api/suppressions
│   │   ├── domains.py          # CRUD /api/domains
│   │   ├── unsubscribe.py      # GET/POST /unsubscribe/:token
│   │   └── dashboard.py        # Dashboard HTML pages + data endpoints
│   ├── templates/              # Jinja2 HTML templates
│   │   ├── base.html           # Layout with Tailwind CDN, nav
│   │   ├── dashboard/
│   │   │   ├── index.html      # Metrics overview + chart
│   │   │   ├── activity.html   # Email activity list
│   │   │   ├── suppressions.html
│   │   │   ├── domains.html
│   │   │   ├── deferred.html
│   │   │   └── message_detail.html
│   │   ├── unsubscribe/
│   │   │   ├── confirm.html
│   │   │   ├── success.html
│   │   │   └── error.html
│   │   └── partials/           # HTMX partial templates
│   │       ├── activity_table.html
│   │       ├── suppression_table.html
│   │       └── domain_list.html
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── email_validator.py  # Email format validation
│   │   ├── sns_validator.py    # SNS signature verification
│   │   └── html_processor.py   # URL rewriting, pixel injection, XSS sanitization
│   └── static/                 # Minimal static assets if needed
│       └── pixel.gif           # 1x1 transparent GIF
├── tests/
│   ├── __init__.py
│   ├── conftest.py             # Fixtures: test client, test DB, mock SES
│   ├── test_email_service.py
│   ├── test_webhook_service.py
│   ├── test_tracking_service.py
│   ├── test_suppression_service.py
│   ├── test_unsubscribe_service.py
│   ├── test_domain_service.py
│   ├── test_sns_validator.py
│   └── test_integration_send.py  # Full send flow integration test
├── .env.example
├── .gitignore
├── requirements.txt
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml          # App + Postgres for local dev
├── PLAN.md
├── CLAUDE.md
└── README.md
```

### Architecture Principles
1. **Routes are thin**: Validate input, call service, return response. No business logic.
2. **Services own business logic**: Testable independently of HTTP.
3. **Models are plain SQLAlchemy**: No business methods. Just schema.
4. **Schemas validate everything**: Pydantic handles request/response validation.
5. **Config is centralized**: One `Settings` class reads all env vars.

---

## Implementation Phases

### Phase 0: Foundation (Day 1 morning) ✅ COMPLETED
**Goal**: Working FastAPI app with DB, can make a request

- [x] Project scaffolding (directories, pyproject.toml, requirements.txt)
- [x] `config.py` with pydantic-settings (all env vars)
- [x] `database.py` with async SQLAlchemy engine
- [x] All SQLAlchemy models
- [x] Alembic init + first migration (all tables)
- [x] `docker-compose.yml` (Postgres + app)
- [x] `main.py` — app factory, health check endpoint
- [x] `.env.example` with all required vars
- [x] Verify: `docker compose up`, hit `/docs`, see Swagger

**Implementation Notes**:
- Renamed `metadata` column to `message_metadata` to avoid SQLAlchemy reserved attribute name
- Created virtual environment and installed all dependencies
- Database verified with all tables, indexes, and constraints created successfully
- Health check and Swagger UI tested and working

**Commit**: `feat: project foundation — FastAPI, DB schema, Docker setup`

### Phase 1: Email Sending (Day 1 afternoon)
**Goal**: Can send an email via API and see it in DB

- [ ] `ses_client.py` — boto3 wrapper for `send_email`
- [ ] `email_service.py` — validation, suppression check, send, store record
- [ ] `POST /api/emails/send` route
- [ ] Pydantic schemas for request/response/error
- [ ] Email format validation utility
- [ ] Retry logic with exponential backoff (tenacity library)
- [ ] Consistent error response format (reusable across all routes)
- [ ] Test: Send email via Swagger UI, verify in DB

**Commit**: `feat: email sending API with validation and retry logic`

### Phase 2: Webhook Processing (Day 2)
**Goal**: Receive SES events and update message status

- [ ] `sns_validator.py` — signature verification (fetch cert, verify with cryptography lib)
- [ ] `webhook_service.py` — parse SNS envelope, extract SES event, route by type
- [ ] `POST /api/webhooks/ses` route
- [ ] Handle subscription confirmation (auto-confirm)
- [ ] Process: Delivery, Bounce, Complaint, DeliveryDelay, Reject events
- [ ] Store events in events table
- [ ] Update message status (state machine logic)
- [ ] Auto-suppress on hard bounce and complaint
- [ ] Deferred handling (set first_deferred_at, track delays)
- [ ] Setup: ngrok, subscribe to SNS topic, test with real events
- [ ] Test: Send email → wait for delivery webhook → verify status updated

**Critical detail**: SNS sends the body as a JSON string inside another JSON object. The outer layer is the SNS envelope (with Type, MessageId, TopicArn, Message, Signature, etc.). The `Message` field is a JSON-stringified SES event. Must parse twice.

**Commit**: `feat: webhook processing with SNS validation and status updates`

### Phase 3: Click & Open Tracking (Day 3)
**Goal**: Track opens and clicks, URLs rewritten in sent emails

- [ ] `html_processor.py` — BeautifulSoup-based URL rewriter
  - Find all `<a href="...">` tags
  - Replace href with `/api/track/click/{message_id}?url={encoded_original}`
  - Skip mailto: and # links
  - Inject tracking pixel `<img>` before `</body>`
- [ ] `tracking_service.py` — record click/open events
- [ ] `GET /api/track/click/:trackingId` — log click, 302 redirect
- [ ] `GET /api/track/open/:trackingId` — log open (first only), return 1x1 GIF
- [ ] Cache-Control headers on open pixel
- [ ] Integrate URL rewriting into email send flow
- [ ] Generate 1x1 transparent GIF (43 bytes, hardcoded base64)
- [ ] Fallback URL for invalid tracking IDs

**Commit**: `feat: click and open tracking with URL rewriting`

### Phase 4: Suppression List (Day 3-4)
**Goal**: Full CRUD suppression management

- [ ] `suppression_service.py` — CRUD operations
- [ ] `GET /api/suppressions` — paginated list with reason filter
- [ ] `POST /api/suppressions` — manual add (validate email, check duplicates)
- [ ] `DELETE /api/suppressions/:email` — remove (204/404)
- [ ] `GET /api/suppressions/check/:email` — simple lookup (fix spec bug)
- [ ] Verify: auto-suppression from webhooks (Phase 2) still works
- [ ] Verify: send API rejects suppressed recipients

**Commit**: `feat: suppression list management API`

### Phase 5: Unsubscribe Flow (Day 4)
**Goal**: Recipients can unsubscribe via secure link

- [ ] `unsubscribe_service.py` — JWT token generation and validation
  - Payload: `{ email, message_id, iat, exp }` (30-day expiry)
  - Sign with HMAC secret from env
- [ ] Integrate unsubscribe link into email send flow (append to HTML)
- [ ] `GET /unsubscribe/:token` — validate, show confirmation page (masked email)
- [ ] `POST /unsubscribe/:token` — process unsubscribe, add to suppressions
- [ ] Jinja templates: confirm.html, success.html, error.html
- [ ] Email masking utility: `john@example.com` → `j***@example.com`
- [ ] Double-submit prevention (check suppression list before processing)
- [ ] List-Unsubscribe header on sent emails (bonus — email clients show unsub button)

**Commit**: `feat: unsubscribe flow with signed tokens`

### Phase 6: Domain Verification (Day 5)
**Goal**: Verify sending domains, enforce on send

- [ ] `domain_service.py` — SES API wrapper for domain operations
- [ ] `POST /api/domains/verify` — call VerifyDomainIdentity + VerifyDomainDkim
- [ ] `GET /api/domains/:domain/records` — return required DNS records
- [ ] `GET /api/domains/:domain/status` — check verification + DKIM status from SES
- [ ] `GET /api/domains` — list all domains from DB
- [ ] `DELETE /api/domains/:domain` — remove from DB only (document decision)
- [ ] Add domain verification check to email send flow
- [ ] Handle pre-verified domain (candidate-test.kubbly.com)

**Commit**: `feat: domain verification and sender authentication`

### Phase 7: Dashboard UI (Day 6-8)
**Goal**: Full admin dashboard with all views

#### 7a: Layout & Metrics Overview
- [ ] `base.html` — Tailwind layout, sidebar nav (Dashboard, Activity, Suppressions, Domains, Deferred)
- [ ] `index.html` — 6 metric cards (Total Sent, Delivery Rate, Open Rate, Click Rate, Bounce Rate, Deferred Count)
- [ ] Dashboard data endpoint: `GET /api/dashboard/metrics?days=7`
- [ ] Chart.js time series: daily email volume (sent, delivered, bounced)

#### 7b: Activity List
- [ ] Paginated table (25/page)
- [ ] Status badges with colors (gray=sent, green=delivered, red=bounced, yellow=deferred, purple=complained, dark=rejected)
- [ ] Click row → message detail page (all events, metadata, timestamps)
- [ ] HTMX pagination (no full page reload)

#### 7c: Suppression List View
- [ ] Table with email, reason, date
- [ ] "Add Email" button → HTMX modal with form
- [ ] "Remove" button with confirmation dialog
- [ ] Pagination

#### 7d: Domain Management
- [ ] List all domains with status badges
- [ ] "Add Domain" → modal form
- [ ] DNS records display (copyable with click)
- [ ] "Check Status" button (HTMX inline refresh)
- [ ] "Delete" with confirmation

#### 7e: Deferred Emails View
- [ ] Filter activity by deferred status
- [ ] Show delay reason, time since first deferral
- [ ] Manual refresh button
- [ ] Note about SES 12-hour auto-retry

**Commit**: `feat: dashboard UI with metrics, activity, and management views`

### Phase 8: Testing (Day 9)
**Goal**: 75%+ coverage, all core logic tested

- [ ] `conftest.py` — async test DB (SQLite in-memory or test Postgres), mock SES client
- [ ] Unit tests:
  - email_service: validation, suppression check, retry logic
  - webhook_service: SNS parsing, all event types, state transitions
  - tracking_service: URL rewriting, pixel injection, first-open-only
  - suppression_service: CRUD, duplicate handling
  - unsubscribe_service: token generation, validation, expiry, masking
  - domain_service: verification flow
  - sns_validator: signature verification
- [ ] Integration test: full send flow (mock SES → verify DB record → simulate webhook → verify status update)
- [ ] Run coverage: `pytest --cov=app --cov-report=html`

**Commit**: `test: unit and integration tests, 75%+ coverage`

### Phase 9: Documentation & Deployment (Day 10)
**Goal**: Deployed, documented, demo-ready

- [ ] README.md:
  - Architecture overview with diagram
  - Tech stack justification
  - Setup instructions (Docker and manual)
  - Environment variables table
  - API endpoints summary
  - Design decisions and trade-offs
  - Testing instructions
- [ ] Swagger docs are auto-generated (verify they're clean)
- [ ] Dockerfile (multi-stage if needed)
- [ ] Deploy to Railway:
  - Provision Postgres
  - Set env vars
  - Run migrations
  - Verify all endpoints work
- [ ] Update ngrok URL → production URL for webhook subscription
- [ ] Smoke test on production

**Commit**: `docs: README, deployment, API documentation`

---

## Status State Machine (Reference)

```
                ┌──────────┐
                │   sent   │
                └────┬─────┘
         ┌───────┬───┼───────┬──────────┐
         ▼       ▼   ▼       ▼          ▼
    delivered  bounced deferred  rejected  (complaint
         │                │                  comes later)
         │                ├──► delivered
         │                └──► bounced
         ▼
     complained
```

Valid transitions:
- `sent → delivered` (Delivery event)
- `sent → bounced` (Bounce event)
- `sent → deferred` (DeliveryDelay event)
- `sent → rejected` (Reject event)
- `deferred → delivered` (Delivery after delay)
- `deferred → bounced` (Bounce after delay)
- `delivered → complained` (Complaint event)

Invalid/ignored transitions (handle gracefully, log warning):
- `bounced → delivered` (shouldn't happen, but don't crash)
- `rejected → anything` (terminal state)
- Duplicate events (idempotent processing)

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| SNS signature validation is tricky | High | Blocks webhooks | Use `requests` to fetch cert, `cryptography` lib to verify. Test with real SNS early. |
| SES sandbox limits | Medium | Can't test at volume | App-level rate limiting. Use allowed recipients list. |
| Async SQLAlchemy gotchas | Medium | Random session errors | Use `async_scoped_session`, ensure sessions are closed. Test early. |
| BeautifulSoup URL rewriting breaks HTML | Low | Mangled emails | Test with various HTML structures. Use `html.parser` not `lxml` for consistency. |
| Chart.js CDN fails | Low | Dashboard looks broken | Pin CDN version, add fallback message. |
| Railway deployment issues | Low | Can't demo | Have Render as backup plan. Docker means it runs anywhere. |

---

## Bonus Features (if time permits)
1. **App-level rate limiting** — Token bucket, show in dashboard
2. **Batch send endpoint** — `POST /api/emails/send-batch` for multiple recipients
3. **Email preview** — Dashboard page to preview HTML before sending
4. **Export metrics** — CSV download of email activity
5. **Dark mode** — Tailwind dark mode toggle on dashboard
6. **List-Unsubscribe header** — RFC 8058 one-click unsubscribe
