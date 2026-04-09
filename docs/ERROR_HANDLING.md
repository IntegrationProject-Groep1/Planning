# Error Handling Reference

## Principles

- **No black holes** — every failure is logged with structured key=value fields.
- **Non-blocking Graph failures** — an Outlook sync failure never nacks a RabbitMQ message. The session is already safe in PostgreSQL.
- **XSD gate** — invalid outgoing XML is blocked before it reaches RabbitMQ. It is logged and never published.
- **Idempotency** — duplicate incoming messages are detected via `message_log` and silently ACKed.
- **Retry with backoff** — publish failures are retried up to 3 times with exponential backoff (1s → 2s → 4s).

---

## Error Catalogue

### 1. Incoming message — parse failure

**Where:** `consumer.py → on_message()`  
**Cause:** Malformed XML, missing namespace, missing required fields.  
**Behaviour:** Message is **nacked without requeue**. Logged at ERROR level.  
**Log example:**
```
Failed to parse message (nack, no requeue)
Content: <broken xml...>
```

---

### 2. Incoming message — duplicate

**Where:** `consumer.py → handle_*()`  
**Cause:** `message_log` already contains the `message_id`.  
**Behaviour:** Message is **ACKed** (safe to discard). Logged at WARNING level.  
**Log example:**
```
Duplicate calendar.invite (already processed): msg-uuid-001
```

---

### 3. Incoming message — handler exception

**Where:** `consumer.py → handle_*()`  
**Cause:** Database error or unexpected exception inside a handler.  
**Behaviour:** Message is **nacked without requeue**. `message_log` is updated to `failed`. Logged at ERROR level with traceback.  
**Log example:**
```
Error handling calendar.invite: connection refused
```

---

### 4. Outgoing message — XSD validation failure

**Where:** `producer.py → _publish_with_validation_and_retry()`  
**Cause:** Built XML does not match the XSD schema for the message type.  
**Behaviour:** **Publish is blocked**. No message is sent to RabbitMQ. Logged at ERROR level.  
**Log example:**
```
Outgoing message blocked: XSD validation failed
| message_type=session_created
| error=Element 'session_id': This element is not expected. ...
```

---

### 5. Outgoing message — RabbitMQ publish failure

**Where:** `producer.py → _publish_with_validation_and_retry()`  
**Cause:** RabbitMQ connection error or channel error.  
**Behaviour:** **Retried up to 3 times** with exponential backoff (1s, 2s, 4s). If all attempts fail, returns `False` and logs at ERROR level.  
**Log example:**
```
Publish attempt 1/3 failed | routing_key=planning.session.created | error=...
Retrying in 1.0s | routing_key=planning.session.created
All 3 publish attempts exhausted | routing_key=planning.session.created | message_type=session_created
```

---

### 6. Graph API — credentials not configured

**Where:** `graph_service.py → _build_client()`  
**Cause:** `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, or `AZURE_CLIENT_SECRET` not set.  
**Behaviour:** Graph sync is **disabled silently** — returns `False`. Consumer continues normally. Logged at WARNING level.  
**Log example:**
```
Graph API not configured — Outlook sync disabled: Graph API credentials not configured. ...
```

---

### 7. Graph API — token acquisition failure

**Where:** `graph_client.py → _get_token()`  
**Cause:** Invalid client credentials or revoked secret.  
**Behaviour:** `GraphClientError` is raised, caught by `GraphService`, recorded in `graph_sync` as `failed`. Logged at ERROR level.  
**Log example:**
```
Graph API create_event failed | session_id=sess-001 | error=Failed to acquire Graph API token: invalid_client – ...
```

---

### 8. Graph API — HTTP error (create / update / cancel)

**Where:** `graph_client.py → _raise_for_status()`  
**Cause:** Non-2xx response from Graph API (403, 404, 500, etc.).  
**Behaviour:** `GraphClientError` raised, caught by `GraphService`, stored in `graph_sync.error_message`. Consumer ACKs the message. Logged at ERROR level.  
**Log example:**
```
Graph API cancel_event failed | session_id=sess-001 | error=cancel_event(event_id=evt-001) failed | status=403 | detail=Access denied
```

---

## Retry / Recovery

| Scenario | Recovery path |
|---|---|
| Publish failure (RabbitMQ) | Automatic retry × 3 with backoff in `producer.py` |
| Graph sync failure | `graph_sync.sync_status = failed` — can be queried and retried manually or by a future background job |
| Invalid outgoing XML | Fix the builder or data upstream; blocked messages do not auto-retry |
| Handler DB error | Message is nacked; safe to re-deliver from RabbitMQ management UI |

---

## Observability

All log lines use structured `key=value` pairs so they are easy to grep or index.

```bash
# Find all failed Graph syncs in the DB
SELECT session_id, error_message, last_synced_at
FROM graph_sync
WHERE sync_status = 'failed'
ORDER BY last_synced_at DESC;

# Find all failed messages
SELECT message_id, message_type, error_details, created_at
FROM message_log
WHERE status = 'failed'
ORDER BY created_at DESC;
```
