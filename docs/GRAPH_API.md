# Microsoft Graph API Integration

## Overview

The planning service uses the Microsoft Graph API to manage Outlook calendar events.  
When a session is created, updated, or deleted, the service creates, updates, or cancels the corresponding Outlook event in the configured mailbox.

---

## Azure App Registration Setup

### Required permission

| Permission | Type | Reason |
|---|---|---|
| `Calendars.ReadWrite` | Application | Create/update/cancel events in the target mailbox without a signed-in user |

Admin consent is required for application permissions.

### Steps

1. Go to **Azure Portal → Entra ID → App registrations → New registration**
2. Name it (e.g. `planning-service`) and click **Register**
3. Note the **Application (client) ID** and **Directory (tenant) ID**
4. Go to **Certificates & secrets → New client secret** — copy the value immediately
5. Go to **API permissions → Add a permission → Microsoft Graph → Application permissions**
6. Add `Calendars.ReadWrite` and click **Grant admin consent**

---

## Environment Variables

| Variable | Description |
|---|---|
| `AZURE_TENANT_ID` | Azure AD tenant ID (`f8cdef31-a31e-4b4a-93e4-5f571e91255a` for this project) |
| `AZURE_CLIENT_ID` | App registration client ID |
| `AZURE_CLIENT_SECRET` | App registration client secret |
| `GRAPH_CALENDAR_USER` | The Planning service's own mailbox (e.g. `planning@desideriushogeschool.nl`). Events are created in **this** calendar — it is the shared Planning calendar, not individual users' calendars. Must belong to your Azure AD tenant. |

Copy `.env.example` to `.env` and fill in these values.

---

## Authentication

Authentication uses the **OAuth2 client credentials flow** (app-only, no user sign-in).  
The `msal` library handles token acquisition and caching automatically.  
Tokens are refreshed transparently before they expire.

---

## Sync Flow

### session_created / calendar.invite received

```
Consumer receives message
  → DB: create/update session
  → GraphService.sync_created()
      → GraphClient.create_event()  (POST /users/{user}/calendar/events)
      → DB: upsert graph_sync (status=synced, event_id stored)
```

### session_updated received

```
Consumer receives message
  → DB: update session
  → GraphService.sync_updated()
      → DB: look up graph_event_id from graph_sync
      → if found: GraphClient.update_event()  (PATCH /users/{user}/calendar/events/{id})
      → if not found: falls back to sync_created (creates a new event)
      → DB: upsert graph_sync (status=synced)
```

### session_deleted received

```
Consumer receives message
  → DB: soft-delete session
  → GraphService.sync_deleted()
      → DB: look up graph_event_id from graph_sync
      → if found: GraphClient.cancel_event()  (POST /events/{id}/cancel)
      → DB: update graph_sync (status=deleted)
      → if not found: no-op (returns True)
```

---

## graph_sync Table

Tracks the mapping between a planning `session_id` and the Graph API `event_id`.

| Column | Type | Description |
|---|---|---|
| `session_id` | VARCHAR PK | Planning session ID |
| `graph_event_id` | VARCHAR | Outlook event ID from Graph API |
| `sync_status` | VARCHAR | `pending` / `synced` / `failed` / `deleted` |
| `last_synced_at` | TIMESTAMPTZ | Timestamp of last successful sync |
| `error_message` | TEXT | Populated when `sync_status = failed` |

Run migration to create it:

```bash
psql postgresql://user:pass@localhost:5433/planning_db < migrations/003_graph_sync.sql
```

---

## Error Handling

- Graph API failures are **non-blocking**: the consumer ACKs the RabbitMQ message even when the Graph call fails. The session is already persisted in PostgreSQL.
- Failed syncs are recorded in `graph_sync` with `sync_status = failed` and the error message stored in `error_message`.
- If credentials are not configured (`AZURE_CLIENT_ID` etc. are empty), Graph sync is silently disabled and a warning is logged. The rest of the service continues normally.
- See [ERROR_HANDLING.md](ERROR_HANDLING.md) for the full error catalogue.

---

## Idempotency

`create_event` sends `session_id` as the Graph API `transactionId` field.  
If the same request is sent twice (e.g. after a retry), Graph API returns the existing event instead of creating a duplicate.
