# Planning Service — Integration Project Groep 1

![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python)
![RabbitMQ](https://img.shields.io/badge/RabbitMQ-3.12-orange?logo=rabbitmq)
![Docker](https://img.shields.io/badge/Docker-Compose-blue?logo=docker)
![CI](https://github.com/IntegrationProject-Groep1/Planning/actions/workflows/ci.yml/badge.svg)

De Planning-service verwerkt sessie-aanvragen van andere teams via RabbitMQ, publiceert sessie-events terug, en maakt via de **Microsoft Graph API** events aan in de Outlook kalender van de gebruiker.

> ⚠️ **Dit project is nog in ontwikkeling.** Niet alle functionaliteit is geïmplementeerd. Deze README kan nog wijzigen naarmate het project vordert.

---

## Centrale Dashboards

- **Log Viewer (Dozzle):** via de link: azureproject:(juiste poort)
- **RabbitMQ Management:** via de link: azureproject:(juiste poort)

---

## Overzicht

```
┌─────────────────────────────────────────────────────────────────┐
│                      Planning Service                           │
│                                                                 │
│  consumer.py                      producer.py                   │
│  Luistert op:                     Publiceert op:                │
│  exchange: calendar.exchange      exchange: planning.exchange   │
│  queue:    planning.calendar      routing:  planning.session    │
│            .invite                          .created            │
│  routing:  calendar.invite                                      │
│                                                                 │
│  health endpoint: :30050 (voor sidecar heartbeat)               │
│                                                                 │
│  [TODO] Microsoft Graph API (OAuth)                             │
│  Gebruiker logt in → access token → event in Outlook kalender   │
└─────────────────────────────────────────────────────────────────┘
                          │
                          ▼
         RabbitMQ Broker — poort 30000
```

---

## Projectstructuur

```
Planning/
├── consumer.py          # Ontvangt calendar.invite berichten van andere teams
├── producer.py          # Publiceert session_created berichten naar andere teams
├── tests/
│   ├── test_consumer.py # Tests voor de consumer
│   └── test_producer.py # Tests voor de producer
├── .env                 # Productie-credentials (niet in git ⚠️)
├── .env.local           # Lokale credentials (niet in git ⚠️)
├── .env.example         # Template — vul aan met eigen credentials
├── docker-compose.yml   # Services orchestratie
├── Dockerfile           # Docker image definitie
└── requirements.txt     # Python dependencies
```

---

## Snel starten

### Vereisten

- Docker Desktop
- Python 3.12+

### 1. Credentials instellen

```bash
cp .env.example .env
```

Vul `.env` in met de productie-credentials (gekregen van Tom/infra).
Zie [Environment variables](#environment-variables) voor een overzicht van alle variabelen.

Voor lokaal ontwikkelen, maak `.env.local` aan op basis van `.env.example` met `RABBITMQ_HOST=localhost` en `RABBITMQ_PORT=5672`.

### 2. Starten

**Productie** (verbinding met remote broker):
```powershell
docker compose up -d
```

**Lokaal** (eigen RabbitMQ container):
```powershell
$env:ENV_FILE=".env.local"; docker compose --profile local up -d
```

### 3. Logs bekijken

```powershell
# Planning service
docker compose logs -f planning-service
```

### 4. Stoppen

```powershell
docker compose down
```

---

## Lokaal ontwikkelen (zonder Docker)

### Virtual environment

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### Consumer starten

```powershell
python consumer.py
```

Verwachte output:
```
INFO:__main__:Health endpoint gestart op poort 30050
INFO:__main__:Consumer gestart | exchange=calendar.exchange | queue=planning.calendar.invite | routing_key=calendar.invite | vhost=/
```

### Producer testen

```powershell
python producer.py
```

Verwachte output:
```
INFO:__main__:Message sent with routing key 'planning.session.created'
INFO:__main__:✓ Message successfully sent to RabbitMQ
```

### End-to-end test

Start de consumer in terminal 1, stuur een testbericht in terminal 2:

```powershell
# Terminal 2
python test_send.py
```

Verwachte output in terminal 1:
```
INFO:__main__:calendar.invite ontvangen | message_id=... | session_id=sess-test-001 | title=Test sessie | ...
```

---

## XML-berichtformaat

Alle XML-veldnamen zijn **snake_case**, enum-waarden zijn **lowercase**. Dit is verplicht door de projectstandaard (v3).

### session_created — Routing key: `planning.session.created`

```xml
<message xmlns="urn:integration:planning:v1">
  <header>
    <message_id>550e8400-e29b-41d4-a716-446655440000</message_id>
    <timestamp>2026-05-15T09:00:00Z</timestamp>
    <source>planning</source>
    <type>session_created</type>
    <version>1.0</version>
    <correlation_id>corr-uuid-hier</correlation_id>
  </header>
  <body>
    <session_id>sess-uuid-001</session_id>
    <title>Keynote: AI in de zorgsector</title>
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

### calendar.invite — Routing key: `calendar.invite` *(inkomend)*

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
    <title>Keynote: AI in de zorgsector</title>
    <start_datetime>2026-05-15T14:00:00Z</start_datetime>
    <end_datetime>2026-05-15T15:00:00Z</end_datetime>
    <location>online</location>
  </body>
</message>
```

---

## RabbitMQ-configuratie

| | Consumer | Producer |
|---|---|---|
| **Exchange** | `calendar.exchange` | `planning.exchange` |
| **Queue** | `planning.calendar.invite` | — |
| **Routing key** | `calendar.invite` | `planning.session.created` |
| **Type** | topic | topic |

**Broker:**

| Omgeving | Host | Poort |
|---|---|---|
| Productie (AMQP) | zie `.env` | `30000` |
| Productie (UI) | zie `.env` | `30001` |
| Lokaal (AMQP) | `localhost` | `5672` |
| Lokaal (UI) | `localhost` | `15672` |

---

## Heartbeat Sidecar

De heartbeat wordt verzorgd door de gedeelde sidecar-image van Team Infra. Die controleert elke seconde of `planning-service:30050` bereikbaar is en stuurt een heartbeat naar RabbitMQ.

De planning-service exposeert een minimale health endpoint op poort **30050** die `ok` teruggeeft.

Status bekijken via de RabbitMQ UI → Exchange `heartbeat`, of in Kibana (Team Controlroom).

---

## Microsoft Graph API *(coming soon)*

De planning-service zal integreren met de **Microsoft Graph API** om events rechtstreeks aan te maken in de Outlook kalender van de gebruiker.

**Vereisten:**
- Azure App Registration (`client_id`, `client_secret`, `tenant_id`) — te verkrijgen bij de prof
- OAuth 2.0 — gebruiker moet inloggen met Microsoft account
- Permission: `Calendars.ReadWrite`

**Flow:**
```
[Gebruiker logt in via Microsoft OAuth]
        ↓
[Planning-service ontvangt access token]
        ↓
[Graph API: POST /me/events]
        ↓
[Event verschijnt in Outlook kalender van de gebruiker]
```

> ⚠️ **Nog niet geïmplementeerd.** Wacht op Azure App Registration credentials van de prof.

---

## Environment variables

| Variable | Verplicht | Beschrijving |
|---|---|---|
| `RABBITMQ_HOST` | ja | Hostnaam van de broker |
| `RABBITMQ_PORT` | ja | AMQP-poort (`30000` prod / `5672` lokaal) |
| `RABBITMQ_USER` | ja | Gebruikersnaam (gekregen van infra) |
| `RABBITMQ_PASS` | ja | Wachtwoord (gekregen van infra) |
| `RABBITMQ_VHOST` | ja | Virtual host (standaard: `/`) |

> Gebruik `.env.example` als basis. Commit **nooit** `.env` of `.env.local` naar git.

---

## Tests

```powershell
# Installeer pytest (eenmalig)
.venv\Scripts\pip install pytest

# Alle tests uitvoeren
.venv\Scripts\pytest tests/ -v
```

Tests dekken:
- XML-generatie en veldvalidatie (producer)
- XML-parsing, ontbrekende velden en foutafhandeling (consumer)
- RabbitMQ ack/nack gedrag (consumer)
- Verbindingsfouten en ontbrekende credentials (producer)

---

## Voor andere teams — berichten sturen naar Planning

Om een `calendar.invite` te sturen naar de planning-service:

```python
channel.exchange_declare(exchange="calendar.exchange", exchange_type="topic", durable=True)
channel.basic_publish(
    exchange="calendar.exchange",
    routing_key="calendar.invite",
    body=xml.encode("utf-8"),
    properties=pika.BasicProperties(content_type="application/xml", delivery_mode=2)
)
```

Verplichte velden in `<body>`: `session_id`, `title`, `start_datetime`, `end_datetime`.

---

## Team Planning

Desideriushogeschool — Integratieproject Groep Planning
