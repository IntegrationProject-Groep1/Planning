# Microsoft Graph API Integration

## Overview

The planning service uses the Microsoft Graph API to manage Outlook calendar events.  
When a user enrolls in a session via `calendar.invite`, the service creates an event in **that user's personal Outlook calendar** using their stored OAuth token.

When a session is updated or deleted system-wide, the corresponding Outlook event is updated or cancelled using the shared service account token.

---

## Authentication Modes

### Per-user (delegated) — primary mode

Used for `calendar.invite` processing. The user's access token is stored after login and used to create events directly in their personal calendar.

Flow:
1. Drupal sends `POST /api/tokens` with the user's Microsoft OAuth tokens after login.
2. Tokens are encrypted with Fernet and stored in the `user_tokens` table.
3. When `calendar.invite` arrives, `TokenService.get_valid_token(user_id)` retrieves the token (auto-refreshing via MSAL if it expires within 5 minutes).
4. `GraphClient` uses that token to call `POST /me/calendar/events`.

### Shared service account — fallback mode

Used for `session_updated` / `session_deleted` (no user context in those messages).  
Requires running `scripts/auth_setup.py` once to persist the MSAL token cache.

---

## Azure App Registration Setup

### Required permissions

| Permission | Type | Reason |
|---|---|---|
| `Calendars.ReadWrite` | Delegated | Create/update/cancel events in a user's personal calendar |
| `User.Read` | Delegated | Read user profile after login |

Admin consent is required for delegated permissions used without a signed-in user session.

### Steps

1. Go to **Azure Portal → Entra ID → App registrations → New registration**
2. Name it (e.g. `planning-service`) and click **Register**
3. Note the **Application (client) ID** and **Directory (tenant) ID**
4. Go to **Certificates & secrets → New client secret** — copy the value immediately
5. Go to **API permissions → Add a permission → Microsoft Graph → Delegated permissions**
6. Add `Calendars.ReadWrite` and `User.Read`, then click **Grant admin consent**
7. Add `http://localhost:5001/getAToken` as a redirect URI (Web type) for `scripts/auth_setup.py`

---

## Environment Variables

| Variable | Description |
|---|---|
| `AZURE_CLIENT_ID` | App registration client ID |
| `AZURE_CLIENT_SECRET` | App registration client secret |
| `TOKEN_CACHE_FILE` | Path to the shared MSAL token cache (default: `token_cache.json`) |
| `TOKEN_ENCRYPTION_KEY` | Fernet key for encrypting per-user tokens in `user_tokens` table |

Copy `.env.example` to `.env` and fill in these values.

**`TOKEN_ENCRYPTION_KEY`** must be generated once and never changed:
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```
If this key changes, all stored tokens become unreadable and every user must re-login.

---

## Shared Token Cache Setup (one-time)

To enable the shared service account fallback, run once:

```bash
python scripts/auth_setup.py
```

Open `http://localhost:5001/login` and sign in with the Planning service mailbox.  
The token cache is saved to `token_cache.json` (path set by `TOKEN_CACHE_FILE`).

---

## Sync Flow

### calendar.invite received (per-user)

```
Consumer receives message
  → DB: create/update session
  → TokenService.get_valid_token(user_id)   [auto-refresh if near expiry]
  → GraphService.sync_created(user_id=...)
      → GraphClient.create_event()           [POST /me/calendar/events]
      → DB: upsert graph_sync (status=synced, event_id stored)
  → publish_calendar_invite_confirmed()      [back to Frontend]
```

### session_updated received

```
Consumer receives message
  → DB: update session
  → GraphService.sync_updated()
      → DB: look up graph_event_id from graph_sync
      → if found: GraphClient.update_event()  [PATCH /calendar/events/{id}]
      → if not found: falls back to sync_created
      → DB: upsert graph_sync (status=synced)
```

### session_deleted received

```
Consumer receives message
  → DB: soft-delete session
  → GraphService.sync_deleted()
      → DB: look up graph_event_id from graph_sync
      → if found: GraphClient.cancel_event()  [POST /events/{id}/cancel]
      → DB: update graph_sync (status=deleted)
      → if not found: no-op (returns True)
```

---

## graph_sync Table

Tracks the mapping between a planning `session_id` and the Graph API `event_id`.  
Created by migration `migrations/003_graph_sync.sql`.

| Column | Type | Description |
|---|---|---|
| `session_id` | VARCHAR PK | Planning session ID |
| `graph_event_id` | VARCHAR | Outlook event ID from Graph API |
| `sync_status` | VARCHAR | `pending` / `synced` / `failed` / `deleted` |
| `last_synced_at` | TIMESTAMPTZ | Timestamp of last successful sync |
| `error_message` | TEXT | Populated when `sync_status = failed` |

## user_tokens Table

Stores per-user OAuth tokens for the delegated flow.  
Created by migration `migrations/004_user_tokens.sql`.

| Column | Type | Description |
|---|---|---|
| `user_id` | VARCHAR PK | Drupal user ID |
| `access_token_enc` | TEXT | Fernet-encrypted access token |
| `refresh_token_enc` | TEXT | Fernet-encrypted refresh token |
| `expires_at` | TIMESTAMPTZ | When the access token expires |
| `updated_at` | TIMESTAMPTZ | Auto-updated on every change |

---

## Error Handling

- Graph API failures are **non-blocking**: the consumer ACKs the RabbitMQ message even when the Graph call fails. The session is already persisted in PostgreSQL.
- Failed syncs are recorded in `graph_sync` with `sync_status = failed` and the error stored in `error_message`.
- If no token is registered for a `user_id`, a warning is logged and Graph sync is skipped.
- If `AZURE_CLIENT_ID` / `AZURE_CLIENT_SECRET` are not configured, the shared fallback is also disabled and a warning is logged. The rest of the service continues normally.
- See [ERROR_HANDLING.md](ERROR_HANDLING.md) for the full error catalogue.

---

## Idempotency

`create_event` sends `session_id` as the Graph API `transactionId` field.  
If the same request is sent twice (e.g. after a retry), Graph API returns the existing event instead of creating a duplicate.
