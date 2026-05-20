"""
Praktische voorbeelden van Master UUID (correlation_id) implementatie.

Dit bestand toont real-world use cases van hoe je Master UUID gebruikt.
"""
from producer import (
    create_session_xml,
    create_session_updated_xml,
    create_session_deleted_xml,
    MasterUUIDManager,
)
from lxml import etree


def extract_message_info(xml_string: str) -> dict:
    """Extraheer belangrijke velden uit XML."""
    root = etree.fromstring(xml_string.encode("utf-8"))
    # Verwijder namespace
    for elem in root.iter():
        elem.tag = etree.QName(elem.tag).localname
    
    return {
        "message_type": root.findtext("header/type"),
        "message_id": root.findtext("header/message_id"),
        "correlation_id": root.findtext("header/correlation_id"),
        "session_id": root.findtext("body/session_id"),
        "title": root.findtext("body/title"),
        "status": root.findtext("body/status"),
    }


# ============================================================================
# VOORBEELD 1: Planning van een keyfnote
# ============================================================================
print("=" * 80)
print("VOORBEELD 1: Planning van een keynote")
print("=" * 80)

SESSION_ID_KEYNOTE = "keynote-ai-2026-05-15"

print("\n📝 STAP 1: Keynote aanmaken")
keynote_created = create_session_xml(
    session_id=SESSION_ID_KEYNOTE,
    title="Keynote: The Future of AI in Healthcare",
    start_datetime="2026-05-15T14:00:00Z",
    end_datetime="2026-05-15T15:00:00Z",
    location="Main Hall",
    max_attendees=500,
    current_attendees=0
)
info = extract_message_info(keynote_created)
print("✓ Keynote aangemaakt")
print(f"  Type: {info['message_type']}")
print(f"  Session ID: {info['session_id']}")
print(f"  Correlation ID: {info['correlation_id']}")

print("\n📝 STAP 2: Meer attendees aanmelden")
keynote_updated_1 = create_session_updated_xml(
    session_id=SESSION_ID_KEYNOTE,
    title="Keynote: The Future of AI in Healthcare",
    start_datetime="2026-05-15T14:00:00Z",
    end_datetime="2026-05-15T15:00:00Z",
    location="Main Hall",
    current_attendees=150
)
info = extract_message_info(keynote_updated_1)
print("✓ Attendees bijgewerkt (150)")
print(f"  Type: {info['message_type']}")
print(f"  Correlation ID: {info['correlation_id']}")

print("\n📝 STAP 3: Nog meer attendees, zaal vol!")
keynote_updated_2 = create_session_updated_xml(
    session_id=SESSION_ID_KEYNOTE,
    title="Keynote: The Future of AI in Healthcare - SOLD OUT",
    start_datetime="2026-05-15T14:00:00Z",
    end_datetime="2026-05-15T15:00:00Z",
    location="Main Hall",
    current_attendees=500,
    status="sold_out"
)
info = extract_message_info(keynote_updated_2)
print("✓ Status bijgewerkt naar SOLD OUT")
print(f"  Type: {info['message_type']}")
print(f"  Correlation ID: {info['correlation_id']}")

print("\n" + "=" * 80)
print("TRACING RESULTAAT: Alle berichten hebben DEZELFDE correlation_id!")
print("Dit stelt je in staat om alle updates van deze keynote samen te traceren.")
print("=" * 80)


# ============================================================================
# VOORBEELD 2: Workshop management (meerdere updates en verwijdering)
# ============================================================================
print("\n\n" + "=" * 80)
print("VOORBEELD 2: Workshop management")
print("=" * 80)

SESSION_ID_WORKSHOP = "workshop-python-advanced"

print("\n📝 STAP 1: Workshop aanmaken")
workshop_created = create_session_xml(
    session_id=SESSION_ID_WORKSHOP,
    title="Advanced Python Programming",
    start_datetime="2026-05-16T10:00:00Z",
    end_datetime="2026-05-16T12:00:00Z",
    location="Room 302",
    max_attendees=30
)
info = extract_message_info(workshop_created)
corr_id_workshop = info['correlation_id']
print("✓ Workshop aangemaakt")
print(f"  Correlation ID: {corr_id_workshop}")

print("\n📝 STAP 2: Locatie wijzigen")
workshop_moved = create_session_updated_xml(
    session_id=SESSION_ID_WORKSHOP,
    title="Advanced Python Programming",
    start_datetime="2026-05-16T10:00:00Z",
    end_datetime="2026-05-16T12:00:00Z",
    location="Room 401",  # Verhuisd!
    current_attendees=15
)
info = extract_message_info(workshop_moved)
print("✓ Locatie gewijzigd naar Room 401")
print(f"  Correlation ID: {info['correlation_id']}")

print("\n📝 STAP 3: Annuleren vanwege instructeur ziekte")
workshop_cancelled = create_session_deleted_xml(
    session_id=SESSION_ID_WORKSHOP,
    reason="Instructor illness",
    deleted_by="event_coordinator@planning.service"
)
info = extract_message_info(workshop_cancelled)
print("✓ Workshop geannuleerd")
print(f"  Correlation ID: {info['correlation_id']}")

print("\n" + "=" * 80)
print("📊 TRACING RESULTAAT:")
print(f"  1. Created  → {corr_id_workshop}")
print(f"  2. Updated  → {MasterUUIDManager.get(SESSION_ID_WORKSHOP)}")
print(f"  3. Deleted  → {MasterUUIDManager.get(SESSION_ID_WORKSHOP)}")
print("\n✓ Alle stappen zijn traceerbaar via dezelfde correlation_id!")
print("=" * 80)


# ============================================================================
# VOORBEELD 3: Parallel sessions (verschillende ID's, verschillende UUID's)
# ============================================================================
print("\n\n" + "=" * 80)
print("VOORBEELD 3: Parallel sessions")
print("=" * 80)

print("\nDrie gelijktijdige sessies worden gepland:\n")

sessions = [
    {
        "id": "parallel-session-1-frontend",
        "title": "Modern Frontend Development",
        "room": "Room 101"
    },
    {
        "id": "parallel-session-2-devops",
        "title": "DevOps Best Practices",
        "room": "Room 102"
    },
    {
        "id": "parallel-session-3-security",
        "title": "Security in Cloud Services",
        "room": "Room 103"
    }
]

correlation_ids = {}

for session in sessions:
    xml = create_session_xml(
        session_id=session["id"],
        title=session["title"],
        start_datetime="2026-05-17T11:00:00Z",
        end_datetime="2026-05-17T12:00:00Z",
        location=session["room"]
    )
    info = extract_message_info(xml)
    correlation_ids[session["id"]] = info['correlation_id']
    print(f"  📍 {session['title']:<40} → {info['correlation_id']}")

print("\n" + "=" * 80)
print("🔍 ANALYSE:")
unique_ids = len(set(correlation_ids.values()))
print(f"  Totaal sessies: {len(sessions)}")
print(f"  Unieke correlation_ids: {unique_ids}")
print("  ✓ Elke sessie heeft zijn eigen correlation_id!")
print("=" * 80)


# ============================================================================
# VOORBEELD 4: Monitoring & Debugging
# ============================================================================
print("\n\n" + "=" * 80)
print("VOORBEELD 4: Debugging met correlation_id")
print("=" * 80)

SESSION_ID_DEBUG = "debug-session-troubleshooting"

print("\n🔧 Stel je voor: Je wilt alle logs van één sessie vinden")
print(f"\nSession ID: {SESSION_ID_DEBUG}")

# Creëer bericht
debug_msg = create_session_xml(
    session_id=SESSION_ID_DEBUG,
    title="Problem Solving Session",
    start_datetime="2026-05-18T15:00:00Z",
    end_datetime="2026-05-18T16:00:00Z",
    location="Conference"
)
info = extract_message_info(debug_msg)
master_uuid = info['correlation_id']

print(f"Master UUID: {master_uuid}")
print("\nJe kunt nu alle logs zoeken met:")
print(f"  grep '{master_uuid}' logs/all.log")
print(f"  journalctl | grep '{master_uuid}'")
print(f"  SELECT * FROM logs WHERE correlation_id = '{master_uuid}'")

print("\nResultaat:")
print("""
  [2026-05-18 15:00:00] DEBUG | correlation_id=abc123... | session_created received
  [2026-05-18 15:05:30] INFO  | correlation_id=abc123... | calendar event created
  [2026-05-18 15:07:15] DEBUG | correlation_id=abc123... | session_updated received  
  [2026-05-18 15:09:45] ERROR | correlation_id=abc123... | calendar sync failed!
  [2026-05-18 15:10:12] INFO  | correlation_id=abc123... | retry attempt 1
  [2026-05-18 15:10:45] INFO  | correlation_id=abc123... | retry successful

🎯 Alle logs voor deze sessie zijn direct traceerbaar!
""")

print("=" * 80)
print("✅ Einde voorbeelden")
print("=" * 80)
