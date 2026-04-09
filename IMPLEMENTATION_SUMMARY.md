# Planning Service — Implementation Summary

## Scope

This document covers the complete implementation of the Planning service:
XML serialization, XSD validation, RabbitMQ publishing/consuming, Microsoft Graph API calendar integration, PostgreSQL persistence, and tests.

For the quick start and project structure see [README.md](README.md).

---

## File Structure

```
Planning/
├── consumer.py               # RabbitMQ consumer (5 handlers + Graph API calls)
├── producer.py               # RabbitMQ publisher (XSD gate + exponential backoff)
├── xml_models.py             # Dataclasses: 6 message types
├── xml_handlers.py           # XML parse (5) + build (4) functions
├── xsd_validator.py          # lxml XSD validation with schema cache
├── calendar_service.py       # PostgreSQL: MessageLog, SessionService, etc.
├── graph_client.py           # MSAL + requests Graph API client
├── graph_service.py          # Graph + graph_sync DB orchestration
│
├── schemas/                  # XSD files — source of truth for outgoing messages
│   ├── calendar_invite.xsd
│   ├── session_created.xsd
│   ├── session_updated.xsd
│   ├── session_deleted.xsd
│   ├── session_view_request.xsd
│   └── session_view_response.xsd
│
├── migrations/
│   ├── 001_initial.sql
│   ├── 002_planning_schema.sql   # sessions, calendar_invites, session_events,
│   │                             # session_view_requests, message_log
│   └── 003_graph_sync.sql        # graph_sync (session_id ↔ graph_event_id)
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
└── docs/
    ├── MESSAGE_CONTRACTS.md      # XML examples and routing keys for all types
    ├── GRAPH_API.md              # Graph API setup, flows, graph_sync table
    └── ERROR_HANDLING.md         # Error catalogue (8 scenarios) + recovery table
```

---

## What Was Implemented

### 1. XML Models (`xml_models.py`)

Dataclasses for all 6 message types with type-safe header/body separation:

| Class | Direction |
|---|---|
| `CalendarInviteMessage` | Incoming |
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
- Schema map covers all 6 message types.

**Note:** `start_datetime`/`end_datetime` in `session_*` body are `xs:string` (not `xs:dateTime`) — this matches the XSD contracts and means the validator accepts any string format for those fields in session messages. `calendar.invite` uses `xs:dateTime` and is stricter.

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

Public API:
- `publish_session_created()`
- `publish_session_updated()`
- `publish_session_deleted()`
- `publish_session_view_response()`

All return `True` on success, `False` on failure.

---

### 5. RabbitMQ Consumer (`consumer.py`)

Listens on two exchanges/queues:

| Queue | Exchange | Routing key |
|---|---|---|
| `planning.calendar.invite` | `calendar.exchange` | `calendar.invite` |
| `planning.session.events` | `planning.exchange` | `planning.session.#` |

**Handlers:**

| Handler | Message type | DB ops | Graph |
|---|---|---|---|
| `handle_calendar_invite` | `calendar.invite` | create session, store invite | `sync_created` |
| `handle_session_created` | `session_created` | upsert session, log event | — |
| `handle_session_updated` | `session_updated` | upsert session, log event | `sync_updated` |
| `handle_session_deleted` | `session_deleted` | soft-delete session, log event | `sync_deleted` |
| `handle_session_view_request` | `session_view_request` | log request | — |

**Guarantees:**
- Idempotency via `message_log` (duplicate messages silently ACKed).
- Graph API failure is **non-blocking** — message is still ACKed.
- Handler exception → nack without requeue + error logged.

---

### 6. Database Service (`calendar_service.py`)

Five service classes using psycopg2 with `DictCursor`:

| Class | Table | Key operations |
|---|---|---|
| `MessageLog` | `message_log` | `log_message()` (idempotency), `update_message_status()` |
| `SessionService` | `sessions` | `create_or_update()`, `delete()`, `get()`, `list_all()` |
| `CalendarInviteService` | `calendar_invites` | `create()`, `update_status()` |
| `SessionEventService` | `session_events` | `log_event()` (audit trail) |
| `SessionViewRequestService` | `session_view_requests` | `log_request()`, `mark_responded()` |

---

### 7. Microsoft Graph API (`graph_client.py` + `graph_service.py`)

**`graph_client.py` — `GraphClient`:**
- MSAL `ConfidentialClientApplication` (client credentials flow, app-only).
- Token cached by MSAL; refreshed automatically on expiry.
- `create_event()` — POST with `transactionId = session_id` (idempotency).
- `update_event()` — PATCH existing event.
- `cancel_event()` — POST `/events/{id}/cancel` with comment.
- `GraphClientError` raised on any failure.

**`graph_service.py` — `GraphService`:**
- `sync_created()` — create Outlook event + upsert `graph_sync`.
- `sync_updated()` — update event; falls back to create if not found in DB.
- `sync_deleted()` — cancel event + mark `graph_sync` as deleted; no-op if not found.
- All methods return `False` and log errors on failure — never crash the consumer.
- If credentials are absent, `_build_client()` returns `None` and sync is skipped.

**`graph_sync` table:**

| Column | Description |
|---|---|
| `session_id` | PK — planning session ID |
| `graph_event_id` | Outlook event ID |
| `sync_status` | `pending` / `synced` / `failed` / `deleted` |
| `error_message` | Populated on failure — enables later retry |

---

### 8. Tests

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

### calendar.invite → Outlook event created

```
RabbitMQ (calendar.exchange, routing: calendar.invite)
  → consumer.py: handle_calendar_invite()
    → MessageLog.log_message()         [idempotency check]
    → SessionService.create_or_update()
    → CalendarInviteService.create()
    → MessageLog.update_message_status("processed")
    → GraphService.sync_created()
        → GraphClient.create_event()   [POST /calendar/events]
        → graph_sync upserted          [status=synced]
    → channel.basic_ack()
```

### session_updated → Outlook event updated

```
RabbitMQ (planning.exchange, routing: planning.session.updated)
  → consumer.py: handle_session_updated()
    → MessageLog.log_message()
    → SessionService.create_or_update()
    → SessionEventService.log_event()  [audit trail]
    → MessageLog.update_message_status("processed")
    → GraphService.sync_updated()
        → graph_sync lookup            [get event_id]
        → GraphClient.update_event()   [PATCH /calendar/events/{id}]
        → graph_sync upserted
    → channel.basic_ack()
```

### Publish outgoing event (session_created)

```
publish_session_created()
  → build_session_created_xml()
  → _publish_with_validation_and_retry()
      → validate_xml()                 [XSD check — blocks if invalid]
      → _publish_message()             [attempt 1]
      → on failure: sleep 1s → attempt 2 → sleep 2s → attempt 3
      → returns True/False
```

---

## Error Handling Summary

See [docs/ERROR_HANDLING.md](docs/ERROR_HANDLING.md) for the full catalogue.

| Scenario | Behaviour |
|---|---|
| Invalid incoming XML | nack without requeue |
| Duplicate message | ACK (idempotency) |
| Handler DB error | nack + log error |
| Invalid outgoing XML | blocked — never published |
| Publish failure | retry ×3 with exponential backoff |
| Graph API credentials absent | warn + skip sync |
| Graph API HTTP error | log + store in `graph_sync.error_message` |

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
| Tests present from the start | ✅ (125+ tests) |
| Idempotency | ✅ (message_log + Graph transactionId) |
| Retry with backoff | ✅ (producer) |
