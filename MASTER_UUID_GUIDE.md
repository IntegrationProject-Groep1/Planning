# Master UUID (Correlation ID) - Implementatiedocumentatie

## 📋 Overzicht

**Master UUID** (ook wel `correlation_id` genoemd) is een unieke identifier die alle gerelateerde berichten van dezelfde sessie aan elkaar koppelt. Dit stelt jouw systeem in staat om de volledige levenscyclus van een sessie te traceren.

## 🎯 Waarom Master UUID nodig is

In een gedistribueerd systeem met meerdere services die berichten uitwisselen, kan het moeilijk zijn om te traceren welke berichten bij elkaar horen. Master UUID lost dit op door een "trace thread" te creëren:

```
Session ID: sess-001
    ↓
    ├─ session_created  → correlation_id: abc123def456
    ├─ session_updated  → correlation_id: abc123def456 (DEZELFDE!)
    ├─ session_updated  → correlation_id: abc123def456 (DEZELFDE!)
    └─ session_deleted  → correlation_id: abc123def456 (DEZELFDE!)

📝 Alle berichten hebben DEZELFDE correlation_id!
```

## 🔧 Hoe het werkt

### 1. **Master UUID Creation** (Eerste keer)
Wanneer je een sessie **aanmaakt** met `create_session_xml()`:
- Er wordt een **NIEUWE Master UUID gegenereerd**
- Deze wordt gekoppeld aan de `session_id` en opgeslagen
- De Master UUID wordt in de `correlation_id` header gezet

```python
# Voorbeeld
created_xml = create_session_xml(
    session_id="sess-001",
    title="Meeting",
    ...
)
# Master UUID: generaatd en opgeslagen
```

### 2. **Master UUID Reuse** (Updates & Deletes)
Wanneer je een sessie **update** of **verwijdert**:
- De **BESTAANDE Master UUID** wordt opgehaald
- Dezelfde UUID wordt in de `correlation_id` header gezet
- Alle berichten horen nu bij elkaar!

```python
# Voorbeeld
updated_xml = create_session_updated_xml(
    session_id="sess-001",  # Dezelfde sessie_id
    title="Meeting (Updated)",
    ...
)
# Master UUID: HERGEBRUIKT van eerder
```

## 💾 Opslag

Master UUIDs worden opgeslagen in `.master_uuids.json` in JSON format:

```json
{
  "sess-001": "a1b2c3d4-e5f6-7890-1234-567890abcdef",
  "sess-002": "f1e2d3c4-b5a6-9876-5432-109876fedcba",
  "sess-003": "12345678-1234-1234-1234-123456789012"
}
```

## 🔄 Workflow

```
┌─────────────────────────────────────────────────────┐
│         1. Sessie aanmaken (create)                 │
│     Genereer NIEUWE Master UUID + sla op            │
│                      ↓                              │
│         2. Sessie updaten (update)                  │
│     Haal BESTAANDE Master UUID op + hergebruik      │
│                      ↓                              │
│         3. Sessie verwijderen (delete)              │
│     Haal BESTAANDE Master UUID op + hergebruik      │
│                      ↓                              │
│    ✅ Alle berichten hebben DEZELFDE UUID!         │
└─────────────────────────────────────────────────────┘
```

## 📚 API-referentie

### `MasterUUIDManager.get_or_create(session_id: str) -> str`
Haal bestaande Master UUID op óf creëer een nieuwe.

```python
master_uuid = MasterUUIDManager.get_or_create("sess-001")
# → "a1b2c3d4-e5f6-7890-1234-567890abcdef"
```

### `MasterUUIDManager.get(session_id: str) -> str | None`
Haal ALLEEN bestaande Master UUID op (geen creatie).

```python
master_uuid = MasterUUIDManager.get("sess-001")
# → "a1b2c3d4-e5f6-7890-1234-567890abcdef" (of None)
```

## 🧪 Testen

Run het test script om de Master UUID functionaliteit te verifiëren:

```bash
python test_master_uuid.py
```

Dit voert uit:
1. ✅ **Test 1**: Dezelfde sessie krijgt dezelfde Master UUID
2. ✅ **Test 2**: Verschillende sessies krijgen verschillende Master UUIDs

## 📊 Logging

De Consumer logt nu ook de `correlation_id`:

```
session_created received | correlation_id=abc123... | message_id=xyz789... | source=planning | ...
session_updated received | correlation_id=abc123... | message_id=123456... | source=planning | ...
session_deleted received | correlation_id=abc123... | message_id=456789... | source=planning | ...
```

Dit stelt je in staat om alle berichten van een sessie te traceren via dezelfde `correlation_id`.

## 🎨 Voordelen

| Voordeel | Beschrijving |
|----------|-------------|
| **Traceability** | Volg alle berichten van een sessie |
| **Debugging** | Eenvoudig gerelateerde logs terugvinden |
| **Idempotentie** | Detecteer duplicaten via correlation_id |
| **Monitoring** | Track sessie lifecycle in monitoring tools |
| **Audittrail** | Compleet audit trail per sessie |

## 🚀 Volgende stappen

1. **Database integratie**: Sla Master UUIDs op in een echte database i.p.v. JSON bestand
2. **Distributed tracing**: Integreer met tools als Jaeger of Zipkin
3. **Consumer propagatie**: Zorg dat consumer de correlation_id doorgeeft aan downstream services
4. **Analytics**: Track correlation_id patterns voor performance analysis

## 📝 Notities

- Master UUIDs worden NOOIT veranderd na creatie
- Elk unieke `session_id` krijgt een unieke Master UUID
- De Master UUID is dezelfde als de `correlation_id` in de message header
- Als een sessie niet bestaat bij update/delete, wordt automatisch een NIEUWE Master UUID gemaakt met een warning
