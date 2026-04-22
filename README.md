# Planning Service — Integration Project Group 1
# Planning Service — Integration Project Group 1

![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python)
![RabbitMQ](https://img.shields.io/badge/RabbitMQ-3.12-orange?logo=rabbitmq)
![Docker](https://img.shields.io/badge/Docker-Compose-blue?logo=docker)
![CI](https://github.com/IntegrationProject-Groep1/Planning/actions/workflows/ci.yml/badge.svg)

The Planning service receives session requests from other teams via RabbitMQ, publishes session events, manages a PostgreSQL session database, and synchronises Outlook calendar events via the **Microsoft Graph API**.

---

## Documentation

| Document | Description |
|---|---|
| [docs/MESSAGE_CONTRACTS.md](docs/MESSAGE_CONTRACTS.md) | All XML message formats, routing keys, and token endpoint |
| [docs/GRAPH_API.md](docs/GRAPH_API.md) | Microsoft Graph API setup, per-user token flow, and graph_sync table |
| [docs/ERROR_HANDLING.md](docs/ERROR_HANDLING.md) | Error catalogue, retry strategy, observability queries |
| [docs/IMPLEMENTATION_SUMMARY.md](docs/IMPLEMENTATION_SUMMARY.md) | Full implementation overview with file structure |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        Planning Service                          │
│                                                                  │
│  consumer.py                       producer.py                   │
│  Listens on:                       Publishes to:                 │
│  calendar.exchange                 planning.exchange             │
│    └─ calendar.invite                └─ planning.calendar        │
│  planning.exchange                        .invite.confirmed      │
│    └─ planning.session.#             └─ planning.session.created │
│                                      └─ planning.session.updated │
│                                      └─ planning.session.deleted │
│                                      └─ planning.session         │
│                                           .view_response         │
│                                                                  │
│  xml_handlers.py  ←→  xsd_validator.py  ←→  schemas/*.xsd       │
│  xml_models.py                                                   │
│                                                                  │
│  calendar_service.py  ←→  PostgreSQL                            │
│  token_service.py     ←→  PostgreSQL (user_tokens)              │
│  graph_service.py     ←→  Microsoft Graph API (Outlook)         │
│                                                                  │
│  REST endpoint: :30050/api/tokens   (token registration)        │
│  Health endpoint: :30050            (GET → 200 ok)              │
└──────────────────────────────────────────────────────────────────┘
                           │
                           ▼
          RabbitMQ Broker — port 30000
```

---

## Project Structure
## Project Structure

```
Planning/
│
├── consumer.py               # RabbitMQ consumer — 5 message handlers + REST token endpoint
├── producer.py               # RabbitMQ publisher — XSD validation + retry
├── xml_models.py             # Dataclasses for all 6 message types
├── xml_handlers.py           # XML parsing and building
├── xsd_validator.py          # XSD validation against schemas/
├── calendar_service.py       # PostgreSQL service layer (5 classes)
├── graph_client.py           # Microsoft Graph API HTTP client (MSAL)
├── graph_service.py          # Graph + DB sync orchestration
├── token_service.py          # Per-user OAuth token storage + auto-refresh
├── dashboard.py              # Sync status dashboard (http://localhost:8088)
│
├── schemas/                  # XSD schema files (one per message type)
│   ├── calendar_invite.xsd            # incoming: enrollment from Frontend
│   ├── calendar_invite_confirmed.xsd  # outgoing: enrollment confirmation to Frontend
│   ├── session_created.xsd
│   ├── session_updated.xsd
│   ├── session_deleted.xsd
│   ├── session_view_request.xsd
│   └── session_view_response.xsd
│
├── migrations/               # PostgreSQL migrations — run in order
│   ├── 001_initial.sql       # Initial schema
│   ├── 002_planning_schema.sql  # Sessions, message_log, audit tables
│   ├── 003_graph_sync.sql    # graph_sync table (session ↔ Outlook event)
│   └── 004_user_tokens.sql   # user_tokens table (per-user encrypted OAuth tokens)
│
├── tests/
│   ├── conftest.py           # Shared fixtures
│   ├── test_xml_handlers.py  # XML parsing and building (25+ tests)
│   ├── test_xsd_validator.py # XSD validation (20+ tests)
│   ├── test_producer.py      # Publisher + XSD gate + retry (15+ tests)
│   ├── test_consumer.py      # Consumer handlers (10+ tests)
│   ├── test_database.py      # DB service CRUD (30+ tests)
│   ├── test_graph_client.py  # Graph API HTTP client (14 tests)
│   └── test_graph_service.py # Graph sync orchestration (13 tests)
│
├── docs/
│   ├── MESSAGE_CONTRACTS.md      # XML examples, routing keys, token endpoint
│   ├── GRAPH_API.md              # Graph API setup and per-user token flow
│   ├── ERROR_HANDLING.md         # Error catalogue and recovery
│   └── IMPLEMENTATION_SUMMARY.md # Full implementation overview
│
├── scripts/                  # One-time / utility scripts (not part of the service)
│   ├── auth_setup.py         # One-time OAuth login to persist shared MSAL token cache
│   ├── test_send.py          # Manual test: sends a calendar.invite to RabbitMQ
│   └── frontend_demo.py      # Local demo of the frontend (http://localhost:8089)
│
├── .env.example              # Environment variable template — copy to .env
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

---

## Quick Start
## Quick Start

### Requirements
### Requirements

- Docker Desktop
- Python 3.12+

### 1. Set credentials

```bash
cp .env.example .env
```

Fill in `.env`:
- RabbitMQ and PostgreSQL credentials
- Azure credentials for Graph API (optional — sync is disabled gracefully if absent)
- Generate `TOKEN_ENCRYPTION_KEY`:
  ```bash
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  ```
- Generate `API_TOKEN_SECRET`:
  ```bash
  python -c "import secrets; print(secrets.token_hex(32))"
  ```

### 2. Start

```powershell
# Production (connects to remote broker)
docker compose up -d

# Local (spins up its own RabbitMQ)
$env:ENV_FILE=".env.local"; docker compose --profile local up -d
```

### 3. Run migrations

```bash
psql postgresql://user:pass@localhost:5433/planning_db < migrations/002_planning_schema.sql
psql postgresql://user:pass@localhost:5433/planning_db < migrations/003_graph_sync.sql
psql postgresql://user:pass@localhost:5433/planning_db < migrations/004_user_tokens.sql
```

### 4. Logs

```powershell
docker compose logs -f planning-service
```

---

## Local Development (without Docker)

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

Start consumer + REST endpoint:
```powershell
.venv\Scripts\python consumer.py
```

Test publisher:
```powershell
.venv\Scripts\python producer.py created
.venv\Scripts\python producer.py updated
.venv\Scripts\python producer.py deleted
```

Send a manual test message:
```powershell
.venv\Scripts\python scripts/test_send.py
```

---

## Tests

```powershell
# All tests
.venv\Scripts\pytest tests/ -v

# By area
.venv\Scripts\pytest tests/test_xsd_validator.py -v
.venv\Scripts\pytest tests/test_producer.py -v
.venv\Scripts\pytest tests/test_xml_handlers.py -v
.venv\Scripts\pytest tests/test_graph_client.py -v
.venv\Scripts\pytest tests/test_graph_service.py -v
.venv\Scripts\pytest tests/test_consumer.py -v
.venv\Scripts\pytest tests/test_database.py -v

# With coverage
.venv\Scripts\pytest tests/ --cov=. --cov-report=html
```

Total: **125+ tests** across 7 test files.

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
## RabbitMQ Configuration

| | Consumer | Producer |
|---|---|---|
| **Exchanges** | `calendar.exchange`, `planning.exchange` | `planning.exchange` |
| **Queues** | `planning.calendar.invite`, `planning.session.events` | — |
| **Routing keys (in)** | `calendar.invite`, `planning.session.#` | — |
| **Routing keys (out)** | — | `planning.calendar.invite.confirmed`, `planning.session.created`, `planning.session.updated`, `planning.session.deleted`, `planning.session.view_response` |

Exchange names are configurable via env vars `CALENDAR_EXCHANGE` and `PLANNING_EXCHANGE`.

| Environment | Host | Port |
|---|---|---|
| Production (AMQP) | see `.env` | `30000` |
| Production (UI) | see `.env` | `30001` |
| Local (AMQP) | `localhost` | `5672` |
| Local (UI) | `localhost` | `15672` |
| Production (AMQP) | see `.env` | `30000` |
| Production (UI) | see `.env` | `30001` |
| Local (AMQP) | `localhost` | `5672` |
| Local (UI) | `localhost` | `15672` |

---

## REST Endpoint — Token Registration

Drupal calls this once per user after OAuth login:

```
POST http://<host>:30050/api/tokens
Authorization: Bearer <API_TOKEN_SECRET>
Content-Type: application/json

{ "user_id": "usr_123", "access_token": "eyJ...", "refresh_token": "0.A...", "expires_in": 3600 }
```

See [docs/MESSAGE_CONTRACTS.md](docs/MESSAGE_CONTRACTS.md#token-registration-post-apitokens) for the full spec.

---

## Environment Variables
## Environment Variables

| Variable | Required | Description |
| Variable | Required | Description |
|---|---|---|
| `RABBITMQ_HOST` | yes | Broker hostname |
| `RABBITMQ_PORT` | yes | AMQP port (`30000` prod / `5672` local) |
| `RABBITMQ_USER` | yes | Username |
| `RABBITMQ_PASS` | yes | Password |
| `RABBITMQ_VHOST` | yes | Virtual host (default: `/`) |
| `CALENDAR_EXCHANGE` | no | Incoming exchange name (default: `calendar.exchange`) |
| `PLANNING_EXCHANGE` | no | Outgoing exchange name (default: `planning.exchange`) |
| `POSTGRES_DB` | yes | Database name |
| `POSTGRES_USER` | yes | Database user |
| `POSTGRES_PASSWORD` | yes | Database password |
| `AZURE_CLIENT_ID` | no | App registration client ID (Graph API) |
| `AZURE_CLIENT_SECRET` | no | App registration client secret (Graph API) |
| `TOKEN_CACHE_FILE` | no | MSAL shared token cache path (default: `token_cache.json`) |
| `TOKEN_ENCRYPTION_KEY` | yes | Fernet key for encrypting stored OAuth tokens |
| `API_TOKEN_SECRET` | yes | Shared secret for `POST /api/tokens` (Drupal → Planning) |

> Never commit `.env` or `.env.local` to git.  
> Graph API variables are optional — if absent, Outlook sync is disabled gracefully.  
> `TOKEN_ENCRYPTION_KEY` must never change once tokens are stored — changing it invalidates all stored tokens.

---

## Dashboards

| Tool | URL |
|---|---|
| RabbitMQ UI (local) | http://localhost:15672 |
| pgAdmin (local) | http://localhost:5050 |
| Health check | http://localhost:30050 |
| **Sync Dashboard** | **http://localhost:8088** |
| **Frontend Demo** | **http://localhost:8089** (run `python scripts/frontend_demo.py`) |

---

## Team

Desideriushogeschool — Integration Project Group 1 — Planning Team
