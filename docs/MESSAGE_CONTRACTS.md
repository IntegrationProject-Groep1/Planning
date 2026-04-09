# Message Contracts

Namespace for all messages: `urn:integration:planning:v1`

All XSD schema files are in [`schemas/`](../schemas/).

---

## Incoming messages

### `calendar.invite`

Exchange: `calendar.exchange` | Routing key: `calendar.invite`

```xml
<message xmlns="urn:integration:planning:v1">
  <header>
    <message_id>msg-uuid</message_id>
    <timestamp>2026-05-15T09:00:00Z</timestamp>
    <source>frontend</source>
    <type>calendar.invite</type>
  </header>
  <body>
    <session_id>sess-uuid-001</session_id>
    <title>Keynote: AI in Healthcare</title>
    <start_datetime>2026-05-15T14:00:00Z</start_datetime>
    <end_datetime>2026-05-15T15:00:00Z</end_datetime>
    <location>online</location>
  </body>
</message>
```

Required body fields: `session_id`, `title`, `start_datetime`, `end_datetime`

---

### `session_view_request`

Exchange: `planning.exchange` | Routing key: `planning.session.view_request`

```xml
<message xmlns="urn:integration:planning:v1">
  <header>
    <message_id>550e8400-e29b-41d4-a716-446655440000</message_id>
    <timestamp>2026-05-15T10:05:00Z</timestamp>
    <source>planning</source>
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

Sent by Planning **after a `calendar.invite` is successfully processed** — i.e. the session is stored in the database and the Outlook calendar event has been created via the Graph API.

Frontend should listen on `planning.exchange` with routing key `planning.calendar.invite.confirmed` to confirm that the enrollment was accepted.

```xml
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

| Field | Type | Description |
|---|---|---|
| `session_id` | string | The session that was enrolled |
| `original_message_id` | string | `message_id` from the incoming `calendar.invite` — use this to match the response to your original request |
| `status` | enum | `confirmed` \| `failed` |

The `correlation_id` in the header matches the one sent in the original `calendar.invite`, so Frontend can correlate request and response.

**Full enrollment flow:**

```
Frontend → calendar.invite → calendar.exchange → planning.calendar.invite queue
    Planning:
        1. Store session in DB
        2. Create Outlook event (Graph API)
        3. Publish calendar.invite.confirmed → planning.exchange
                                                └─ planning.calendar.invite.confirmed
Frontend ← calendar.invite.confirmed ←─────────────────────────────────────────
```

---

### `session_created`

Exchange: `planning.exchange` | Routing key: `planning.session.created`

```xml
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

### Sending a `calendar.invite` (enrollment)

Publish to `calendar.exchange` with routing key `calendar.invite`:

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

Required body fields: `session_id`, `title`, `start_datetime`, `end_datetime`.  
Optional: `location`. Include a `correlation_id` in the header to match the confirmation response.

### Receiving the confirmation (`calendar.invite.confirmed`)

After Planning processes the enrollment and creates the Outlook event, it publishes a confirmation on `planning.exchange`. Subscribe to receive it:

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

Match the response to your original request using `original_message_id` (equals your sent `message_id`) or `correlation_id`.
