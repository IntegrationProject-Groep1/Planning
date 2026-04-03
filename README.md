# Planning Service — Integration Project Group 1

![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python)
![RabbitMQ](https://img.shields.io/badge/RabbitMQ-3.12-orange?logo=rabbitmq)
![Docker](https://img.shields.io/badge/Docker-Compose-blue?logo=docker)
![CI](https://github.com/IntegrationProject-Groep1/Planning/actions/workflows/ci.yml/badge.svg)

The Planning service processes session requests from other teams via RabbitMQ, publishes session events back, and creates events in the users Outlook calendar via the **Microsoft Graph API**.

> ⚠️ **This project is still under development.** Not all functionality has been implemented. This README may change as the project progresses.

---

## Central Dashboards

- **Log Viewer (Dozzle):** via the link: azureproject:(correct port)
- **RabbitMQ Management:** via the link: azureproject:(correct port)

---

## Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                      Planning Service                           │
│                                                                 │
│  consumer.py                      producer.py                   │
│  Listens on:                      Publishes on:                 │
│  exchange: calendar.exchange      exchange: planning.exchange   │
│  queue:    planning.calendar      routing:  planning.session    │
│            .invite                          .created            │
│  routing:  calendar.invite                                      │
│                                                                 │
│  health endpoint: :30050 (for sidecar heartbeat)                │
│                                                                 │
│  [TODO] Microsoft Graph API (OAuth)                             │
│  User logs in → access token → event in Outlook calendar        │
└─────────────────────────────────────────────────────────────────┘
                          │
                          ▼
         RabbitMQ Broker — port 30000
```

---

## Project Structure

```
Planning/
├── consumer.py          # Receives calendar.invite messages from other teams
├── producer.py          # Publishes session_created messages to other teams
├── tests/
│   ├── test_consumer.py # Tests for the consumer
│   └── test_producer.py # Tests for the producer
├── .env                 # Production credentials (not in git ⚠️)
├── .env.local           # Local credentials (not in git ⚠️)
├── .env.example         # Template — fill in with your own credentials
├── docker-compose.yml   # Services orchestration
├── Dockerfile           # Docker image definition
└── requirements.txt     # Python dependencies
```

---

## Quick Start

### Requirements

- Docker Desktop
- Python 3.12+

### 1. Set Credentials

```bash
cp .env.example .env
```

Fill in `.env` with the production credentials (obtained from Tom/infra).
See [Environment variables](#environment-variables) for an overview of all variables.

For local development, create `.env.local` based on `.env.example` with `RABBITMQ_HOST=localhost` and `RABBITMQ_PORT=5672`.

### 2. Start

**Production** (connection with remote broker):
```powershell
docker compose up -d
```

**Local** (own RabbitMQ container):
```powershell
$env:ENV_FILE=".env.local"; docker compose --profile local up -d
```

### 3. View Logs

```powershell
# Planning service
docker compose logs -f planning-service
```

### 4. Stop

```powershell
docker compose down
```

---

## Local Development (without Docker)

### Virtual environment

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### Start Consumer

```powershell
python consumer.py
```

Expected output:
```
INFO:__main__:Health endpoint started on port 30050
INFO:__main__:Consumer started | exchange=calendar.exchange | queue=planning.calendar.invite | routing_key=calendar.invite | vhost=/
```

### Test Producer

```powershell
python producer.py
```

Expected output:
```
INFO:__main__:Message sent with routing key 'planning.session.created'
INFO:__main__:✓ Message successfully sent to RabbitMQ
```

### End-to-end test

Start the consumer in terminal 1, send a test message in terminal 2:

```powershell
# Terminal 2
python test_send.py
```

Expected output in terminal 1:
```
INFO:__main__:calendar.invite received | message_id=... | session_id=sess-test-001 | title=Test session | ...
```

---

## XML Message Format

All XML field names are **snake_case**, enum values are **lowercase**. This is mandatory per project standard (v3).

### session_created — Routing key: `planning.session.created`

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

### session_updated — Routing key: `planning.session.updated`

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

### session_deleted — Routing key: `planning.session.deleted`

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

### calendar.invite — Routing key: `calendar.invite` *(incoming)*

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

### XSD schemas used by the service

- `xsd/session_created.xsd`
- `xsd/session_updated.xsd`
- `xsd/session_deleted.xsd`
- `xsd/session_view_request.xsd`
- `xsd/session_view_response.xsd`
- `xsd/calendar_invite.xsd`

Validation behavior:

- `producer.py`: validates known outgoing message types (`session_created`, `session_updated`, `session_deleted`, `session_view_request`) against their XSD before publish.
- `consumer.py`: validates incoming messages (`calendar.invite`, `session_created`, `session_updated`, `session_deleted`, `session_view_request`) against their XSD before processing.

---

## RabbitMQ Configuration

| | Consumer | Producer |
|---|---|---|
| **Exchange** | `calendar.exchange` | `planning.exchange` |
| **Queue** | `planning.calendar.invite` | — |
| **Routing key(s)** | `calendar.invite`, `planning.session.created`, `planning.session.updated`, `planning.session.deleted`, `planning.session.view.request` | `planning.session.created`, `planning.session.updated`, `planning.session.deleted`, `planning.session.view.request`, `planning.session.view.response` |
| **Type** | topic | topic |

**Broker:**

| Environment | Host | Port |
|---|---|---|
| Production (AMQP) | see `.env` | `30000` |
| Production (UI) | see `.env` | `30001` |
| Local (AMQP) | `localhost` | `5672` |
| Local (UI) | `localhost` | `15672` |

---

## Heartbeat Sidecar

The heartbeat is handled by Team Infra's shared sidecar image. It checks every second whether `planning-service:30050` is reachable and sends a heartbeat to RabbitMQ.

The planning service exposes a minimal health endpoint on port **30050** that returns `ok`.

View status via the RabbitMQ UI → Exchange `heartbeat`, or in Kibana (Team Controlroom).

---

## Microsoft Graph API *(coming soon)*

The planning service will integrate with the **Microsoft Graph API** to create events directly in the user's Outlook calendar.

**Requirements:**
- Azure App Registration (`client_id`, `client_secret`, `tenant_id`) — obtainable from the professor
- OAuth 2.0 — user must log in with Microsoft account
- Permission: `Calendars.ReadWrite`

**Flow:**
```
[User logs in via Microsoft OAuth]
        ↓
[Planning service receives access token]
        ↓
[Graph API: POST /me/events]
        ↓
[Event appears in user's Outlook calendar]
```

> ⚠️ **Not yet implemented.** Waiting for Azure App Registration credentials from the professor.

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `RABBITMQ_HOST` | yes | Hostname of the broker |
| `RABBITMQ_PORT` | yes | AMQP port (`30000` prod / `5672` local) |
| `RABBITMQ_USER` | yes | Username (obtained from infra) |
| `RABBITMQ_PASS` | yes | Password (obtained from infra) |
| `RABBITMQ_VHOST` | yes | Virtual host (default: `/`) |

> Use `.env.example` as a basis. **Never** commit `.env` or `.env.local` to git.

---

## Tests

```powershell
# Install pytest (once)
.venv\Scripts\pip install pytest

# Run all tests
.venv\Scripts\pytest tests/ -v
```

Tests cover:
- XML generation and field validation (producer)
- XML parsing, missing fields, and error handling (consumer)
- RabbitMQ ack/nack behavior (consumer)
- Connection errors and missing credentials (producer)

---

## For Other Teams — Sending Messages to Planning

To send a `calendar.invite` to the planning service:

```python
channel.exchange_declare(exchange="calendar.exchange", exchange_type="topic", durable=True)
channel.basic_publish(
    exchange="calendar.exchange",
    routing_key="calendar.invite",
    body=xml.encode("utf-8"),
    properties=pika.BasicProperties(content_type="application/xml", delivery_mode=2)
)
```

Required fields in `<body>`: `session_id`, `title`, `start_datetime`, `end_datetime`.

---

## Team Planning

Desiderius University of Applied Sciences — Integration Project Group Planning
