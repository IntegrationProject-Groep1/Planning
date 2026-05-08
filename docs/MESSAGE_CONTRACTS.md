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
| `user_id` | yes | User ID — must match the `user_id` value sent later in `frontend.to.planning.calendar.invite` messages |
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

All messages from Frontend to Planning follow the naming convention: `frontend.to.planning.<domain>.<action>`

---

### `frontend.to.planning.calendar.invite`

Exchange: `calendar.exchange` | Routing key: `frontend.to.planning.calendar.invite`

**When:** A user enrolls in an existing session. Planning creates an Outlook calendar event and generates an ICS feed link (for non-Outlook users).

**IMPORTANT:** This message is exclusively for end users joining sessions. It MUST include a `user_id`.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<message xmlns="urn:integration:planning:v1">
  <header>
    <message_id>550e8400-e29b-41d4-a716-446655440000</message_id>
    <timestamp>2026-05-15T14:00:00Z</timestamp>
    <source>frontend</source>
    <type>calendar.invite</type>
  </header>
  <body>
    <session_id>sess-uuid-001</session_id>
    <title>Keynote: AI in Healthcare</title>
    <start_datetime>2026-05-15T14:00:00Z</start_datetime>
    <end_datetime>2026-05-15T15:00:00Z</end_datetime>
    <location>Zaal A</location>
    <user_id>user-uuid-123</user_id>
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
| `user_id` | yes | User ID — must match the value sent to `POST /api/tokens`. Without a valid `user_id` no Outlook event is created. |

---

### `frontend.to.planning.session.create`

Exchange: `planning.exchange` | Routing key: `frontend.to.planning.session.create`

**When:** An admin creates a new session in Drupal. Planning registers the session in the database and responds with `planning.to.frontend.session.created`.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<message xmlns="urn:integration:planning:v1">
  <header>
    <message_id>550e8400-e29b-41d4-a716-446655440000</message_id>
    <timestamp>2026-05-15T14:00:00Z</timestamp>
    <source>frontend</source>
    <type>session_create_request</type>
    <version>1.0</version>
  </header>
  <body>
    <session_id>sess-uuid-001</session_id>
    <title>Keynote: AI in Healthcare</title>
    <start_datetime>2026-05-15T14:00:00Z</start_datetime>
    <end_datetime>2026-05-15T15:00:00Z</end_datetime>
    <location>Zaal A</location>
    <session_type>keynote</session_type>
    <status>published</status>
    <max_attendees>150</max_attendees>
  </body>
</message>
```

| Field | Required | Description |
|---|---|---|
| `session_id` | yes | Unique session identifier |
| `title` | yes | Session title |
| `start_datetime` | yes | ISO 8601 UTC |
| `end_datetime` | yes | ISO 8601 UTC |
| `location` | no | Venue name |
| `session_type` | no | Type of session |
| `status` | no | Session status |
| `max_attendees` | no | Maximum attendees |

---

### `frontend.to.planning.session.update`

Exchange: `planning.exchange` | Routing key: `frontend.to.planning.session.update`

**When:** An admin modifies a session in Drupal. Planning updates the database and responds with `planning.to.frontend.session.updated`.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<message xmlns="urn:integration:planning:v1">
  <header>
    <message_id>550e8400-e29b-41d4-a716-446655440000</message_id>
    <timestamp>2026-05-15T14:00:00Z</timestamp>
    <source>frontend</source>
    <type>session_update_request</type>
    <version>1.0</version>
  </header>
  <body>
    <session_id>sess-uuid-001</session_id>
    <title>Keynote: AI 2026</title>
    <start_datetime>2026-05-15T14:00:00Z</start_datetime>
    <end_datetime>2026-05-15T15:00:00Z</end_datetime>
    <location>Zaal A</location>
    <session_type>keynote</session_type>
    <status>published</status>
    <max_attendees>150</max_attendees>
  </body>
</message>
```

---

### `frontend.to.planning.session.delete`

Exchange: `planning.exchange` | Routing key: `frontend.to.planning.session.delete`

**When:** An admin deletes a session in Drupal. Planning marks it deleted and responds with `planning.to.frontend.session.deleted`.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<message xmlns="urn:integration:planning:v1">
  <header>
    <message_id>550e8400-e29b-41d4-a716-446655440000</message_id>
    <timestamp>2026-05-15T14:00:00Z</timestamp>
    <source>frontend</source>
    <type>session_delete_request</type>
    <version>1.0</version>
  </header>
  <body>
    <session_id>sess-uuid-001</session_id>
    <reason>cancelled</reason>
  </body>
</message>
```

---

### `frontend.to.planning.session.view`

Exchange: `planning.exchange` | Routing key: `frontend.to.planning.session.view`

**When:** Frontend requests all sessions (or a specific session) via RabbitMQ. Planning responds with `planning.to.frontend.session.view.response`.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<message xmlns="urn:integration:planning:v1">
  <header>
    <message_id>550e8400-e29b-41d4-a716-446655440000</message_id>
    <timestamp>2026-05-15T14:00:00Z</timestamp>
    <source>frontend</source>
    <type>session_view_request</type>
    <version>1.0</version>
    <correlation_id>corr-uuid-here</correlation_id>
  </header>
  <body>
    <session_id>sess-uuid-001</session_id>   <!-- optional: omit to fetch all sessions -->
  </body>
</message>
```

---

## Outgoing messages

All messages from Planning to Frontend follow the naming convention: `planning.to.frontend.<domain>.<action>`

All outgoing messages are validated against their XSD before publishing.  
See [ERROR_HANDLING.md](ERROR_HANDLING.md#4-outgoing-message--xsd-validation-failure) for what happens when validation fails.

---

### `planning.to.frontend.calendar.invite.confirmed`

Exchange: `calendar.exchange` | Routing key: `planning.to.frontend.calendar.invite.confirmed`

**When:** Planning has successfully processed the enrollment (Outlook event created, ICS feed generated).

```xml
<?xml version="1.0" encoding="UTF-8"?>
<message xmlns="urn:integration:planning:v1">
  <header>
    <message_id>550e8400-e29b-41d4-a716-446655440000</message_id>
    <timestamp>2026-05-15T14:00:01Z</timestamp>
    <source>planning</source>
    <type>calendar.invite.confirmed</type>
    <version>1.0</version>
    <correlation_id>corr-uuid-from-original-invite</correlation_id>
  </header>
  <body>
    <session_id>sess-uuid-001</session_id>
    <original_message_id>msg-uuid-of-the-calendar-invite</original_message_id>
    <status>confirmed</status>
    <ics_url>http://…/ical/user-uuid-123?token=…</ics_url>
  </body>
</message>
```

| Field | Description |
|---|---|
| `session_id` | Session the user enrolled in |
| `original_message_id` | `message_id` from the incoming `frontend.to.planning.calendar.invite` |
| `status` | `confirmed` or `failed` |
| `ics_url` | ICS calendar feed link (for non-Outlook users) |

---

### `planning.to.frontend.session.created`

Exchange: `planning.exchange` | Routing key: `planning.to.frontend.session.created`

**When:** A session has been created in Planning (after receiving `frontend.to.planning.session.create`).

```xml
<?xml version="1.0" encoding="UTF-8"?>
<message xmlns="urn:integration:planning:v1">
  <header>
    <message_id>550e8400-e29b-41d4-a716-446655440000</message_id>
    <timestamp>2026-05-15T14:00:01Z</timestamp>
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
    <location>Zaal A</location>
    <session_type>keynote</session_type>
    <status>published</status>
    <max_attendees>150</max_attendees>
    <current_attendees>0</current_attendees>
  </body>
</message>
```

---

### `planning.to.frontend.session.updated`

Exchange: `planning.exchange` | Routing key: `planning.to.frontend.session.updated`

**When:** A session has been updated in Planning (after receiving `frontend.to.planning.session.update`).

Same structure as `planning.to.frontend.session.created`, with `type=session_updated` and updated field values.

---

### `planning.to.frontend.session.deleted`

Exchange: `planning.exchange` | Routing key: `planning.to.frontend.session.deleted`

**When:** A session has been deleted in Planning (after receiving `frontend.to.planning.session.delete`).

```xml
<?xml version="1.0" encoding="UTF-8"?>
<message xmlns="urn:integration:planning:v1">
  <header>
    <message_id>550e8400-e29b-41d4-a716-446655440000</message_id>
    <timestamp>2026-05-15T14:00:01Z</timestamp>
    <source>planning</source>
    <type>session_deleted</type>
    <version>1.0</version>
    <correlation_id>corr-uuid-here</correlation_id>
  </header>
  <body>
    <session_id>sess-uuid-001</session_id>
    <reason>cancelled</reason>
    <deleted_by>frontend</deleted_by>
  </body>
</message>
```

---

### `planning.to.frontend.session.view.response`

Exchange: `planning.exchange` | Routing key: `planning.to.frontend.session.view.response`

**When:** Frontend requested sessions via `frontend.to.planning.session.view`. Planning responds with matching sessions.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<message xmlns="urn:integration:planning:v1">
  <header>
    <message_id>550e8400-e29b-41d4-a716-446655440000</message_id>
    <timestamp>2026-05-15T14:00:01Z</timestamp>
    <source>planning</source>
    <type>session_view_response</type>
    <version>1.0</version>
    <correlation_id>corr-uuid-from-request</correlation_id>
  </header>
  <body>
    <request_message_id>req-uuid-001</request_message_id>
    <requested_session_id>sess-uuid-001</requested_session_id>
    <status>ok</status>
    <session_count>2</session_count>
    <sessions>
      <session>
        <session_id>sess-uuid-001</session_id>
        <title>Keynote: AI in Healthcare</title>
        <start_datetime>2026-05-15T14:00:00Z</start_datetime>
        <end_datetime>2026-05-15T15:00:00Z</end_datetime>
        <location>Zaal A</location>
        <session_type>keynote</session_type>
        <status>published</status>
        <max_attendees>150</max_attendees>
        <current_attendees>25</current_attendees>
      </session>
    </sessions>
  </body>
</message>
```

| Field | Description |
|---|---|
| `status` | `ok` or `not_found` |
| `session_count` | Number of sessions in the response |
| `correlation_id` | Matches the request's `correlation_id` |

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

### Step 2 — Send a `frontend.to.planning.calendar.invite` (enrollment)

```python
import pika

channel.exchange_declare(exchange="calendar.exchange", exchange_type="topic", durable=True)
channel.basic_publish(
    exchange="calendar.exchange",
    routing_key="frontend.to.planning.calendar.invite",
    body=xml_string.encode("utf-8"),
    properties=pika.BasicProperties(
        content_type="application/xml",
        delivery_mode=2,
    ),
)
```

Include `<user_id>user-uuid-123</user_id>` in the body and a `correlation_id` in the header.

### Step 3 — Receive the confirmation

```python
channel.exchange_declare(exchange="calendar.exchange", exchange_type="topic", durable=True)
queue = channel.queue_declare(queue="", exclusive=True).method.queue
channel.queue_bind(
    queue=queue,
    exchange="calendar.exchange",
    routing_key="planning.to.frontend.calendar.invite.confirmed",
)
channel.basic_consume(queue=queue, on_message_callback=your_handler)
```

Match the response using `original_message_id` or `correlation_id`.

### Receive all session events

Bind with `planning.to.frontend.session.#` to get created, updated, and deleted in one queue:

```python
channel.exchange_declare(exchange="planning.exchange", exchange_type="topic", durable=True)
queue = channel.queue_declare(queue="", exclusive=True).method.queue
channel.queue_bind(
    queue=queue,
    exchange="planning.exchange",
    routing_key="planning.to.frontend.session.#",
)
channel.basic_consume(queue=queue, on_message_callback=your_handler)
```
