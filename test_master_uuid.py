"""
Test script om Master UUID (correlation_id) functionaliteit te demonstreren.
Dit toont aan dat alle berichten van dezelfde sessie dezelfde Master UUID hebben.
"""
import json
from pathlib import Path
from lxml import etree
from producer import (
    create_session_xml,
    create_session_updated_xml,
    create_session_deleted_xml,
    MasterUUIDManager,
)


def extract_correlation_id(xml_string: str) -> str:
    """Extraheer correlation_id uit XML."""
    root = etree.fromstring(xml_string.encode("utf-8"))
    # Verwijder namespace voor eenvoudige parsing
    for elem in root.iter():
        elem.tag = etree.QName(elem.tag).localname
    return root.findtext("header/correlation_id", default="NIET GEVONDEN")


def test_master_uuid_consistency():
    """Test dat dezelfde sessie_id altijd dezelfde Master UUID krijgt."""
    print("=" * 70)
    print("TEST: Master UUID Consistency")
    print("=" * 70)
    
    SESSION_ID = "test-session-12345"
    
    # Leeg de bestaande data
    master_file = Path(__file__).resolve().parent / ".master_uuids.json"
    if master_file.exists():
        master_file.unlink()
    
    # 1. CREATED - Genereert nieuwe Master UUID
    print("\n1️⃣ Bericht: session_created")
    created_xml = create_session_xml(
        session_id=SESSION_ID,
        title="Test Session",
        start_datetime="2026-05-15T14:00:00Z",
        end_datetime="2026-05-15T15:00:00Z",
        location="online"
    )
    correlation_id_created = extract_correlation_id(created_xml)
    print(f"   Correlation ID: {correlation_id_created}")
    print(f"   Master UUID opgeslagen: {MasterUUIDManager.get(SESSION_ID)}")
    
    # 2. UPDATED - Gebruiker dezelfde Master UUID
    print("\n2️⃣ Bericht: session_updated")
    updated_xml = create_session_updated_xml(
        session_id=SESSION_ID,
        title="Test Session (Updated)",
        start_datetime="2026-05-15T14:00:00Z",
        end_datetime="2026-05-15T16:00:00Z",
        location="online"
    )
    correlation_id_updated = extract_correlation_id(updated_xml)
    print(f"   Correlation ID: {correlation_id_updated}")
    
    # 3. DELETED - Gebruiker dezelfde Master UUID
    print("\n3️⃣ Bericht: session_deleted")
    deleted_xml = create_session_deleted_xml(
        session_id=SESSION_ID,
        reason="Test verwijdering"
    )
    correlation_id_deleted = extract_correlation_id(deleted_xml)
    print(f"   Correlation ID: {correlation_id_deleted}")
    
    # Validatie
    print("\n" + "=" * 70)
    print("VALIDATIE RESULTAAT")
    print("=" * 70)
    
    all_same = (correlation_id_created == correlation_id_updated == correlation_id_deleted)
    
    if all_same:
        print(f"✅ SUCCES: Alle berichten hebben dezelfde Master UUID!")
        print(f"   Master UUID: {correlation_id_created}")
        return True
    else:
        print("❌ FOUT: Correlation IDs zijn NIET hetzelfde!")
        print(f"   Created:  {correlation_id_created}")
        print(f"   Updated:  {correlation_id_updated}")
        print(f"   Deleted:  {correlation_id_deleted}")
        return False


def test_different_sessions():
    """Test dat verschillende sessies ook verschillende Master UUIDs krijgen."""
    print("\n\n" + "=" * 70)
    print("TEST: Verschillende Sessies → Verschillende Master UUIDs")
    print("=" * 70)
    
    # Leeg de bestaande data
    master_file = Path(__file__).resolve().parent / ".master_uuids.json"
    if master_file.exists():
        master_file.unlink()
    
    sessions = []
    for i in range(1, 4):
        session_id = f"session-{i}"
        xml = create_session_xml(
            session_id=session_id,
            title=f"Session {i}",
            start_datetime="2026-05-15T14:00:00Z",
            end_datetime="2026-05-15T15:00:00Z",
            location="online"
        )
        corr_id = extract_correlation_id(xml)
        sessions.append((session_id, corr_id))
        print(f"   Session {i}: {corr_id}")
    
    # Validatie
    print("\n" + "=" * 70)
    print("VALIDATIE RESULTAAT")
    print("=" * 70)
    
    correlation_ids = [corr_id for _, corr_id in sessions]
    all_different = len(correlation_ids) == len(set(correlation_ids))
    
    if all_different:
        print("✅ SUCCES: Alle sessies hebben VERSCHILLENDE Master UUIDs!")
        return True
    else:
        print("❌ FOUT: Sommige sessies delen dezelfde Master UUID!")
        return False


def show_master_uuid_storage():
    """Toon de opgeslagen Master UUIDs."""
    print("\n\n" + "=" * 70)
    print("Master UUID Storage (.master_uuids.json)")
    print("=" * 70)
    
    master_file = Path(__file__).resolve().parent / ".master_uuids.json"
    if master_file.exists():
        with open(master_file, "r") as f:
            data = json.load(f)
        print(json.dumps(data, indent=2))
    else:
        print("(Bestand bestaat nog niet)")


if __name__ == "__main__":
    print("\n" + "🧪 MASTER UUID TEST SUITE 🧪".center(70))
    
    # Test 1: Consistency
    test1_passed = test_master_uuid_consistency()
    
    # Test 2: Different sessions
    test2_passed = test_different_sessions()
    
    # Toon opgeslagen data
    show_master_uuid_storage()
    
    # Summary
    print("\n\n" + "=" * 70)
    print("SAMENVATTING")
    print("=" * 70)
    print(f"Test 1 (Consistency):       {'✅ PASSED' if test1_passed else '❌ FAILED'}")
    print(f"Test 2 (Different UUIDs):   {'✅ PASSED' if test2_passed else '❌ FAILED'}")
    
    if test1_passed and test2_passed:
        print("\n🎉 Alle tests geslaagd!")
    else:
        print("\n⚠️ Sommige tests zijn mislukt!")
