# Planning Service — Implementation Summary

## Scope

This document covers the complete implementation of the Planning service:
XML serialization, XSD validation, RabbitMQ publishing/consuming, Microsoft Graph API calendar integration, per-user OAuth token management, PostgreSQL persistence, and tests.

For the quick start and project structure see [README.md](../README.md).

---

## File Structure

```
Planning/
│
├── consumer.py               # RabbitMQ consumer (5 handlers) + REST POST /api/tokens
├── producer.py               # RabbitMQ publisher (XSD gate + exponential backoff)
├── xml_models.py             # Dataclasses: 6 message types
├── xml_handlers.py           # XML parse (5) + build (4) functions
├── xsd_validator.py          # lxml XSD validation with schema cache
├── calendar_service.py       # PostgreSQL: MessageLog, SessionService, etc.
├── graph_client.py           # MSAL + requests Graph API client
├── graph_service.py          # Graph + graph_sync DB orchestration
├── token_service.py          # Per-user OAuth token storage + auto-refresh (Fernet)
├── dashboard.py              # HTML sync status dashboard (:8088)
│
├── schemas/                  # XSD files — source of truth for message contracts
│   ├── calendar_invite.xsd
│   ├── calendar_invite_confirmed.xsd
│   ├── session_created.xsd
│   ├── session_updated.xsd
│   ├── session_deleted.xsd
│   ├── session_view_request.xsd
│   └── session_view_response.xsd
│
├── migrations/               # Run in order on first deploy
│   ├── 001_initial.sql
│   ├── 002_planning_schema.sql   # sessions, calendar_invites, session_events,
│   │                             # session_view_requests, message_log
│   ├── 003_graph_sync.sql        # graph_sync (session_id ↔ graph_event_id)
│   └── 004_user_tokens.sql       # user_tokens (per-user encrypted OAuth tokens)
│
├── tests/
│   ├── conftest.py               # Shared XML fixtures + mock helpers
│   ├── test_xml_handlers.py      # XML parsing and building (25+ tests)
│   ├── test_xsd_validator.py     # XSD validation (20 tests)
│   ├── test_producer.py          # Publisher: XSD gate + retry backoff (15+ tests)
│   ├── test_consumer.py          # Consumer handlers + routing (10+ tests)
│   ├── test_database.py          # DB CRUD for all service classes (30+ tests)
│   ├── test_graph_client.py      # GraphClient: create/update/cancel/token (14 tests)
│   └── test_graph_service.py     # GraphService: sync flows + consumer ACK (13 tests)
│
├── docs/
│   ├── MESSAGE_CONTRACTS.md      # XML examples, routing keys, token endpoint spec
│   ├── GRAPH_API.md              # Graph API setup, per-user token flow, graph_sync table
│   ├── ERROR_HANDLING.md         # Error catalogue (8 scenarios) + recovery table
│   └── IMPLEMENTATION_SUMMARY.md # This file
│
└── scripts/                  # One-time / utility scripts — not part of the service runtime
    ├── auth_setup.py         # One-time OAuth login to persist shared MSAL token cache
    ├── test_send.py          # Sends a manual calendar.invite to RabbitMQ for testing
    └── frontend_demo.py      # Simulates the frontend UI (http://localhost:8089)
```

---

## What Was Implemented

### 1. XML Models (`xml_models.py`)

Dataclasses for all 6 message types with type-safe header/body separation:

| Class | Direction |
|---|---|
| `CalendarInviteMessage` | Incoming |
| `CalendarInviteConfirmedMessage` | Outgoing |
| `SessionCreatedMessage` | Outgoing |
| `SessionUpdatedMessage` | Outgoing |
| `SessionDeletedMessage` | Outgoing |
| `SessionViewRequestMessage` | Incoming |
| `SessionViewResponseMessage` | Outgoing |

---

### 2. XML Handlers (`xml_handlers.py`)

**Parsers (incoming):**
- `parse_calendar_invite()` — `calendar.invite`
- `parse_session_created()` — `session_created`
- `parse_session_updated()` — `session_updated`
- `parse_session_deleted()` — `session_deleted`
- `parse_session_view_request()` — `session_view_request`
- `parse_message()` — generic router by type field

**Builders (outgoing):**
- `build_calendar_invite_confirmed_xml()`
- `build_session_created_xml()`
- `build_session_updated_xml()`
- `build_session_deleted_xml()`
- `build_session_view_response_xml()`

All builders produce XML in the `urn:integration:planning:v1` namespace with a generated `message_id` (UUID) and `timestamp` (UTC).

---

### 3. XSD Validation (`xsd_validator.py` + `schemas/`)

- Loads XSD files from `schemas/` once and caches them.
- `validate_xml(xml, message_type)` → `(bool, error_str | None)`
- `validate_or_raise(xml, message_type)` → raises `ValueError` if invalid.
- Schema map covers all 7 message types.

---

### 4. RabbitMQ Publishing (`producer.py`)

Each outgoing message goes through `_publish_with_validation_and_retry()`:

```
build XML
  → XSD validation (blocked + logged if invalid — no publish)
    → _publish_message() attempt 1
      → on failure: sleep 1s → attempt 2 → sleep 2s → attempt 3
        → on all failures: log ERROR, return False
```

Exchange name is read from `PLANNING_EXCHANGE` env var (default: `planning.exchange`).

Public API:
- `publish_calendar_invite_confirmed()`
- `publish_session_created()`
- `publish_session_updated()`
- `publish_session_deleted()`
- `publish_session_view_response()`

All return `True` on success, `False` on failure.

---

### 5. RabbitMQ Consumer + REST Endpoint (`consumer.py`)

**RabbitMQ — listens on two exchanges/queues:**

| Queue | Exchange | Routing key |
|---|---|---|
| `planning.calendar.invite` | `calendar.exchange` | `calendar.invite` |
| `planning.session.events` | `planning.exchange` | `planning.session.#` |

Exchange names are read from `CALENDAR_EXCHANGE` and `PLANNING_EXCHANGE` env vars.

**Message handlers:**

| Handler | Message type | DB ops | Graph |
|---|---|---|---|
| `handle_calendar_invite` | `calendar.invite` | create session, store invite | `sync_created` with user_id |
| `handle_session_created` | `session_created` | upsert session, log event | — |
| `handle_session_updated` | `session_updated` | upsert session, log event | `sync_updated` |
| `handle_session_deleted` | `session_deleted` | soft-delete session, log event | `sync_deleted` |
| `handle_session_view_request` | `session_view_request` | log request | — |

**REST endpoint — `POST /api/tokens` (port 30050):**

Called once per user after OAuth login. Receives access + refresh tokens from Drupal, encrypts them with Fernet, and stores them in `user_tokens`. Requires `Authorization: Bearer <API_TOKEN_SECRET>`.

**Guarantees:**
- Idempotency via `message_log` (duplicate messages silently ACKed).
- Graph API failure is **non-blocking** — message is still ACKed.
- Handler exception → nack without requeue + error logged.

---

### 6. Per-User Token Service (`token_service.py`)

Manages OAuth tokens per Drupal user for the Graph API delegated flow.

| Method | Description |
|---|---|
| `TokenService.store(user_id, access_token, refresh_token, expires_at)` | Encrypt with Fernet and upsert into `user_tokens` |
| `TokenService.get_valid_token(user_id)` | Return a valid access token, refreshing via MSAL if expiry < 5 min |

Called by `POST /api/tokens` (store) and `graph_service._build_client()` (retrieve).  
Requires `TOKEN_ENCRYPTION_KEY` env var (Fernet key) — generate once, never change.

---

### 7. Database Service (`calendar_service.py`)

Five service classes using psycopg2 with `DictCursor`:

| Class | Table | Key operations |
|---|---|---|
| `MessageLog` | `message_log` | `log_message()` (idempotency), `update_message_status()` |
| `SessionService` | `sessions` | `create_or_update()`, `delete()`, `get()`, `list_all()` |
| `CalendarInviteService` | `calendar_invites` | `create()`, `update_status()` |
| `SessionEventService` | `session_events` | `log_event()` (audit trail) |
| `SessionViewRequestService` | `session_view_requests` | `log_request()`, `mark_responded()` |

---

### 8. Microsoft Graph API (`graph_client.py` + `graph_service.py`)

**`graph_client.py` — `GraphClient`:**
- Two auth modes: per-user token (injected directly) or shared MSAL file cache.
- `create_event()` — POST with `transactionId = session_id` (idempotency).
- `update_event()` — PATCH existing event.
- `cancel_event()` — POST `/events/{id}/cancel` with comment.
- `GraphClientError` raised on any failure.

**`graph_service.py` — `GraphService`:**
- `_build_client(user_id)` — looks up the user's token via `TokenService`, falls back to shared MSAL cache if no `user_id`.
- `sync_created(user_id=...)` — create Outlook event in the user's calendar + upsert `graph_sync`.
- `sync_updated()` — update event; falls back to create if not found in DB.
- `sync_deleted()` — cancel event + mark `graph_sync` as deleted; no-op if not found.
- All methods return `False` and log errors on failure — never crash the consumer.

**`graph_sync` table:**

| Column | Description |
|---|---|
| `session_id` | PK — planning session ID |
| `graph_event_id` | Outlook event ID |
| `sync_status` | `pending` / `synced` / `failed` / `deleted` |
| `error_message` | Populated on failure — enables later retry |

---

### 9. Database Schema Overview

| Table | Migration | Purpose |
|---|---|---|
| `sessions` | 002 | Source of truth for each session |
| `calendar_invites` | 002 | Enrollment: which user registered for which session |
| `session_events` | 002 | Audit trail of all session changes |
| `session_view_requests` | 002 | Tracking of incoming view requests |
| `message_log` | 002 | Idempotency — prevents double-processing |
| `graph_sync` | 003 | Maps `session_id` ↔ Outlook `event_id` |
| `user_tokens` | 004 | Per-user encrypted OAuth tokens |

---

### 10. Tests

| File | Area | Count |
|---|---|---|
| `test_xml_handlers.py` | XML parsing + building | 25+ |
| `test_xsd_validator.py` | XSD validation (valid, invalid, edge cases) | 20 |
| `test_producer.py` | Publisher, XSD gate, retry backoff | 15+ |
| `test_consumer.py` | Handlers, routing, ack/nack | 10+ |
| `test_database.py` | DB CRUD, idempotency, status updates | 30+ |
| `test_graph_client.py` | GraphClient: HTTP, token, errors | 14 |
| `test_graph_service.py` | GraphService: sync flows, consumer ACK | 13 |
| **Total** | | **125+** |

Run all:
```bash
.venv\Scripts\pytest tests/ -v
```

---

## Message Flow Diagrams

### calendar.invite → Outlook event created (per-user)

```
Drupal → POST /api/tokens  (one-time at login)
           → TokenService.store(user_id, access_token, refresh_token)
           → encrypted in user_tokens table

RabbitMQ (calendar.exchange, routing: calendar.invite)
  → consumer.py: handle_calendar_invite()
    → MessageLog.log_message()            [idempotency check]
    → SessionService.create_or_update()
    → CalendarInviteService.create()
    → MessageLog.update_message_status("processed")
    → GraphService.sync_created(user_id=msg.body.user_id)
        → TokenService.get_valid_token()  [auto-refresh if needed]
        → GraphClient.create_event()      [POST /me/calendar/events]
        → graph_sync upserted             [status=synced]
    → publish_calendar_invite_confirmed() [ACK back to Frontend]
    → channel.basic_ack()
```

### session_updated → Outlook event updated

```
RabbitMQ (planning.exchange, routing: planning.session.updated)
  → consumer.py: handle_session_updated()
    → MessageLog.log_message()
    → SessionService.create_or_update()
    → SessionEventService.log_event()     [audit trail]
    → MessageLog.update_message_status("processed")
    → GraphService.sync_updated()
        → graph_sync lookup               [get event_id]
        → GraphClient.update_event()      [PATCH /calendar/events/{id}]
        → graph_sync upserted
    → channel.basic_ack()
```

### Publish outgoing event (session_created)

```
publish_session_created()
  → build_session_created_xml()
  → _publish_with_validation_and_retry()
      → validate_xml()                    [XSD check — blocks if invalid]
      → _publish_message()                [attempt 1]
      → on failure: sleep 1s → attempt 2 → sleep 2s → attempt 3
      → returns True/False
```

---

## Error Handling Summary

See [ERROR_HANDLING.md](ERROR_HANDLING.md) for the full catalogue.

| Scenario | Behaviour |
|---|---|
| Invalid incoming XML | nack without requeue |
| Duplicate message | ACK (idempotency) |
| Handler DB error | nack + log error |
| Invalid outgoing XML | blocked — never published |
| Publish failure | retry ×3 with exponential backoff |
| Graph API credentials absent | warn + skip sync |
| Graph API HTTP error | log + store in `graph_sync.error_message` |
| Token not registered for user | warn + skip Graph sync |
| Token refresh failure | RuntimeError logged, Graph sync skipped |
| `POST /api/tokens` wrong secret | 401 Unauthorized |

---

## Definition of Done — Status

| Requirement | Status |
|---|---|
| Outgoing messages validated against XSD | ✅ |
| Invalid outgoing messages logged / quarantine flow | ✅ |
| Error handling documented | ✅ |
| Event data per message type documented | ✅ |
| All code, comments, docs in English | ✅ |
| RabbitMQ messaging works correctly | ✅ |
| Microsoft Graph API calendar integration | ✅ |
| Per-user OAuth token storage + auto-refresh | ✅ |
| REST endpoint for token registration | ✅ |
| Auth on token endpoint (shared secret) | ✅ |
| Tests present from the start | ✅ (125+ tests) |
| Idempotency | ✅ (message_log + Graph transactionId) |
| Retry with backoff | ✅ (producer) |
