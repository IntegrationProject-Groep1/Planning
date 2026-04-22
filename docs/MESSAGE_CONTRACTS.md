# Message Contracts

Namespace for all messages: `urn:integration:planning:v1`

All XSD schema files are in [`schemas/`](../schemas/).

---

## Token Registration — `POST /api/tokens`

Before any calendar sync can happen, Drupal must register the user's OAuth tokens once after login.

```
POST http://<planning-service-host>:30050/api/tokens
Authorization: Bearer <API_TOKEN_SECRET>
Content-Type: application/json
```

**Request body:**
```json
{
  "user_id":       "usr_123",
  "access_token":  "eyJ...",
  "refresh_token": "0.A...",
  "expires_in":    3600
}
```

| Field | Required | Description |
|---|---|---|
| `user_id` | yes | Drupal internal user ID — same value used in `calendar.invite` XML |
| `access_token` | yes | Microsoft OAuth access token |
| `refresh_token` | yes | Microsoft OAuth refresh token |
| `expires_in` | no | Seconds until access token expires (default: 3600) |

**Responses:**

| Status | Meaning |
|---|---|
| `200` | `{ "status": "ok", "user_id": "usr_123" }` |
| `400` | Missing required field — `{ "error": "..." }` |
| `401` | Missing or wrong `Authorization` header |
| `500` | Internal error |

Tokens are encrypted at rest (Fernet). The service refreshes them automatically when they expire.

---

## Incoming messages

### `calendar.invite`

Exchange: `calendar.exchange` | Routing key: `calendar.invite`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<message xmlns="urn:integration:planning:v1">
  <header>
    <message_id>550e8400-e29b-41d4-a716-446655440000</message_id>
    <timestamp>2026-05-15T09:00:00Z</timestamp>
    <source>drupal-frontend</source>
    <type>calendar.invite</type>
    <version>1.0</version>
    <correlation_id>corr-uuid-here</correlation_id>
  </header>
  <body>
    <session_id>sess-uuid-001</session_id>
    <title>Keynote: AI in Healthcare</title>
    <start_datetime>2026-05-15T14:00:00Z</start_datetime>
    <end_datetime>2026-05-15T15:00:00Z</end_datetime>
    <location>Aula A - Campus Jette</location>
    <user_id>usr_123</user_id>
  </body>
</message>
```

| Field | Required | Description |
|---|---|---|
| `session_id` | yes | Session the user is enrolling in |
| `title` | yes | Session title |
| `start_datetime` | yes | ISO 8601 UTC |
| `end_datetime` | yes | ISO 8601 UTC |
| `location` | no | Venue name |
| `user_id` | yes | Drupal user ID — must match the value sent to `POST /api/tokens`. Without a valid `user_id` no Outlook event is created. |

---

### `session_view_request`

Exchange: `calendar.exchange` | Routing key: `calendar.invite`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<message xmlns="urn:integration:planning:v1">
  <header>
    <message_id>550e8400-e29b-41d4-a716-446655440000</message_id>
    <timestamp>2026-05-15T10:05:00Z</timestamp>
    <source>drupal-frontend</source>
    <type>session_view_request</type>
    <version>1.0</version>
    <correlation_id>corr-uuid-here</correlation_id>
  </header>
  <body>
    <session_id>sess-uuid-001</session_id>
  </body>
</message>
```

`session_id` is optional — omit it to request all sessions.

---

## Outgoing messages

All outgoing messages are validated against their XSD before publishing.  
See [ERROR_HANDLING.md](ERROR_HANDLING.md#4-outgoing-message--xsd-validation-failure) for what happens when validation fails.

### `calendar.invite.confirmed`

Exchange: `planning.exchange` | Routing key: `planning.calendar.invite.confirmed`  
XSD: [`schemas/calendar_invite_confirmed.xsd`](../schemas/calendar_invite_confirmed.xsd)

Sent after a `calendar.invite` is successfully processed and the Outlook event is created.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<message xmlns="urn:integration:planning:v1">
  <header>
    <message_id>550e8400-e29b-41d4-a716-446655440000</message_id>
    <timestamp>2026-05-15T09:00:05Z</timestamp>
    <source>planning</source>
    <type>calendar.invite.confirmed</type>
    <version>1.0</version>
    <correlation_id>corr-uuid-from-original-invite</correlation_id>
  </header>
  <body>
    <session_id>sess-uuid-001</session_id>
    <original_message_id>msg-uuid-of-the-calendar-invite</original_message_id>
    <status>confirmed</status>
  </body>
</message>
```

| Field | Description |
|---|---|
| `session_id` | The session that was enrolled |
| `original_message_id` | `message_id` from the incoming `calendar.invite` |
| `status` | `confirmed` or `failed` |

The `correlation_id` matches the one sent in the original `calendar.invite`.

**Full enrollment flow:**

```
Frontend → POST /api/tokens (once at login)

Frontend → calendar.invite → calendar.exchange
    Planning:
        1. Store session in DB
        2. Look up user token (TokenService)
        3. Create Outlook event in user's calendar (Graph API)
        4. Publish calendar.invite.confirmed → planning.exchange
Frontend ← calendar.invite.confirmed ←─────────────────────────
```

---

### `session_created`

Exchange: `planning.exchange` | Routing key: `planning.session.created`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<message xmlns="urn:integration:planning:v1">
  <header>
    <message_id>550e8400-e29b-41d4-a716-446655440000</message_id>
    <timestamp>2026-05-15T09:00:00Z</timestamp>
    <source>planning</source>
    <type>session_created</type>
    <version>1.0</version>
    <correlation_id>corr-uuid-here</correlation_id>
  </header>
  <body>
    <session_id>sess-uuid-001</session_id>
    <title>Keynote: AI in Healthcare</title>
    <start_datetime>2026-05-15T14:00:00Z</start_datetime>
    <end_datetime>2026-05-15T15:00:00Z</end_datetime>
    <location>Aula A - Campus Jette</location>
    <session_type>keynote</session_type>
    <status>published</status>
    <max_attendees>120</max_attendees>
    <current_attendees>0</current_attendees>
  </body>
</message>
```

---

### `session_updated`

Exchange: `planning.exchange` | Routing key: `planning.session.updated`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<message xmlns="urn:integration:planning:v1">
  <header>
    <message_id>550e8400-e29b-41d4-a716-446655440000</message_id>
    <timestamp>2026-05-15T09:30:00Z</timestamp>
    <source>planning</source>
    <type>session_updated</type>
    <version>1.0</version>
    <correlation_id>corr-uuid-here</correlation_id>
  </header>
  <body>
    <session_id>sess-uuid-001</session_id>
    <title>Keynote: AI in Healthcare (Updated)</title>
    <start_datetime>2026-05-15T14:30:00Z</start_datetime>
    <end_datetime>2026-05-15T15:30:00Z</end_datetime>
    <location>Aula A - Campus Jette</location>
    <session_type>keynote</session_type>
    <status>published</status>
    <max_attendees>150</max_attendees>
    <current_attendees>25</current_attendees>
  </body>
</message>
```

---

### `session_deleted`

Exchange: `planning.exchange` | Routing key: `planning.session.deleted`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<message xmlns="urn:integration:planning:v1">
  <header>
    <message_id>550e8400-e29b-41d4-a716-446655440000</message_id>
    <timestamp>2026-05-15T10:00:00Z</timestamp>
    <source>planning</source>
    <type>session_deleted</type>
    <version>1.0</version>
    <correlation_id>corr-uuid-here</correlation_id>
  </header>
  <body>
    <session_id>sess-uuid-001</session_id>
    <reason>cancelled</reason>
    <deleted_by>planning-admin</deleted_by>
  </body>
</message>
```

---

### `session_view_response`

Exchange: `planning.exchange` | Routing key: `planning.session.view_response`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<message xmlns="urn:integration:planning:v1">
  <header>
    <message_id>550e8400-e29b-41d4-a716-446655440000</message_id>
    <timestamp>2026-05-15T10:05:01Z</timestamp>
    <source>planning</source>
    <type>session_view_response</type>
    <version>1.0</version>
    <correlation_id>corr-uuid-here</correlation_id>
  </header>
  <body>
    <request_message_id>req-uuid-001</request_message_id>
    <requested_session_id>sess-uuid-001</requested_session_id>
    <status>ok</status>
    <session_count>1</session_count>
    <sessions>
      <session>
        <session_id>sess-uuid-001</session_id>
        <title>Keynote: AI in Healthcare</title>
        <start_datetime>2026-05-15T14:00:00Z</start_datetime>
        <end_datetime>2026-05-15T15:00:00Z</end_datetime>
        <location>Aula A - Campus Jette</location>
        <session_type>keynote</session_type>
        <status>published</status>
        <max_attendees>120</max_attendees>
        <current_attendees>25</current_attendees>
      </session>
    </sessions>
  </body>
</message>
```

`status` is either `ok` or `not_found`.

---

## Integration guide for other teams

### Step 1 — Register tokens (once per user at login)

```python
import requests

requests.post(
    "http://<planning-host>:30050/api/tokens",
    headers={"Authorization": f"Bearer {API_TOKEN_SECRET}"},
    json={
        "user_id": "usr_123",
        "access_token": ms_access_token,
        "refresh_token": ms_refresh_token,
        "expires_in": 3600,
    },
)
```

### Step 2 — Send a `calendar.invite` (enrollment)

```python
import pika

channel.exchange_declare(exchange="calendar.exchange", exchange_type="topic", durable=True)
channel.basic_publish(
    exchange="calendar.exchange",
    routing_key="calendar.invite",
    body=xml_string.encode("utf-8"),
    properties=pika.BasicProperties(
        content_type="application/xml",
        delivery_mode=2,
    ),
)
```

Include `<user_id>usr_123</user_id>` in the body and a `correlation_id` in the header.

### Step 3 — Receive the confirmation

```python
channel.exchange_declare(exchange="planning.exchange", exchange_type="topic", durable=True)
queue = channel.queue_declare(queue="", exclusive=True).method.queue
channel.queue_bind(
    queue=queue,
    exchange="planning.exchange",
    routing_key="planning.calendar.invite.confirmed",
)
channel.basic_consume(queue=queue, on_message_callback=your_handler)
```

Match the response using `original_message_id` or `correlation_id`.

### Receive all session events

Bind with `planning.session.#` to get created, updated, and deleted in one queue:

```python
channel.queue_bind(queue=queue, exchange="planning.exchange", routing_key="planning.session.#")
```
