# Planning Service - Heartbeat

Heartbeat service for the university planning system. Regularly publishes a heartbeat message to the RabbitMQ broker to signal that the service is active and operational.

## 📋 Description

This service:
- ✅ Connects to RabbitMQ using credentials from `.env`
- ✅ Publishes an XML message every 1 second to the `heartbeat` exchange
- ✅ Includes status information: uptime, Outlook connectivity, general status
- ✅ Uses routing key `heartbeat.planning` for topic-based routing
- ✅ Runs inside Docker alongside RabbitMQ in `docker-compose`

## 🚀 Quick Start

### Requirements
- Docker and docker-compose installed
- Python 3.12+ (for local development)

### 1. Initial Setup

Copy `.env.example` to `.env` with real values:

```bash
cp .env.example .env
```

Edit `.env`:
```env
RABBITMQ_HOST=localhost
RABBITMQ_PORT=5672
RABBITMQ_USER=planning_rabbitmq
RABBITMQ_PASS=IsPl22
```

### 2. Start Services with Docker

```bash
docker compose up -d
```

This starts:
- **RabbitMQ** on `localhost:5672` (AMQP) and `:15672` (Management UI)
- **Planning Service** which automatically publishes heartbeats

### 3. Verify it Works

Open the RabbitMQ management panel:
```
http://localhost:15672
```

You should see:
- Exchange `heartbeat` (type: topic)
- Messages being published to `heartbeat.planning`

### 4. Stop Services

```bash
docker compose down
```

---

## 💻 Local Development (without Docker)

### 1. Create Virtual Environment

```bash
python -m venv .venv
.venv\Scripts\activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Ensure RabbitMQ is Running

```bash
docker compose up -d rabbitmq
```

### 4. Run the Service

```bash
python heartbeat.py
```

You should see:
```
Heartbeat started...
Heartbeat sent: 2026-03-28 18:30:36.087304
Heartbeat sent: 2026-03-28 18:30:37.088944
...
```

Press `Ctrl+C` to stop.

---

## 📦 Project Structure

```
Planning/
├── .gitignore           # Files to ignore in git
├── .dockerignore        # Files to ignore in Docker
├── .env.example         # Environment variables template
├── .env                 # Environment variables (do not version ⚠️)
├── requirements.txt     # Python dependencies
├── docker-compose.yml   # Services orchestration
├── Dockerfile          # Service Docker image
├── heartbeat.py        # Main service code
└── README.md           # This file
```

---

## 📨 Heartbeat Message Format

The service publishes XML messages in this format:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<message xmlns="urn:integration:heartbeat:v1">
    <header>
        <message_id>550e8400-e29b-41d4-a716-446655440000</message_id>
        <timestamp>2026-03-28T18:30:36.087304+00:00</timestamp>
        <source>planning</source>
        <type>heartbeat</type>
        <hostname>my-machine</hostname>
    </header>
    <body>
        <status>online</status>
        <outlook_api_connected>true</outlook_api_connected>
        <rabbitmq_connected>true</rabbitmq_connected>
        <uptime>145</uptime>
    </body>
</message>
```

### Fields

**Header:**
- `message_id`: Unique UUID for each message
- `timestamp`: ISO 8601 UTC timestamp
- `source`: Always "planning"
- `type`: Always "heartbeat"
- `hostname`: Name of the host running the service

**Body:**
- `status`: "online" (degraded/offline in case of error)
- `outlook_api_connected`: true/false - Outlook API connectivity
- `rabbitmq_connected`: true/false - RabbitMQ connectivity
- `uptime`: Seconds since service started

---

## 🔌 RabbitMQ Configuration

- **Exchange:** `heartbeat` (type: `topic`, durable)
- **Routing Key:** `heartbeat.planning`
- **Protocol:** AMQP 0.9.1

To listen to these messages from another service:
```python
channel.exchange_declare(exchange='heartbeat', exchange_type='topic', durable=True)
queue = channel.queue_declare(queue='', exclusive=True, auto_delete=True)
channel.queue_bind(exchange='heartbeat', queue=queue.method.queue, routing_key='heartbeat.*')
```

---

## 🔐 Security

⚠️ **IMPORTANT:**
- **DO NOT** version `.env` with real credentials
- `.env.example` contains only templates without values
- Credentials are loaded from environment variables in CI/CD
- In production, use secrets management (HashiCorp Vault, AWS Secrets Manager, etc.)

---

## 📊 Monitoring

View logs in real-time:

```bash
docker compose logs -f planning-service
```

View only RabbitMQ logs:
```bash
docker compose logs -f rabbitmq
```

---

## ⚙️ Environment Variables

```env
RABBITMQ_HOST=localhost           # RabbitMQ broker host
RABBITMQ_PORT=5672               # AMQP port
RABBITMQ_USER=planning_rabbitmq   # Authentication username
RABBITMQ_PASS=IsPl22              # Authentication password
```

---

## 🧪 Testing

Test connectivity manually:

```python
python -c "from dotenv import load_dotenv; import os; load_dotenv(); print('USER:', os.getenv('RABBITMQ_USER'))"
```

Verify RabbitMQ server responds:

```bash
telnet localhost 5672
```

---

## 📝 Technical Notes

- Heartbeat interval: **1 second**
- XML format: **UTF-8**
- Namespace: `urn:integration:heartbeat:v1`
- All field names: **snake_case**
- Boolean values: **lowercase** (true/false)
- pika library: Blocking connection, infinite loop

---

## 🤝 Team

This is a project from the Planning team at the university.

---

## 📄 License

Internal - University
