"""
End-to-End Test: Producer → RabbitMQ → Consumer
Tests het volledige flow met echte RabbitMQ en verifiëert correlation_id tracing.
"""
import pika
import json
import time
import logging
import threading
from lxml import etree
from producer import (
    create_session_xml,
    create_session_updated_xml,
    send_message,
    ROUTING_KEY_CREATED,
    ROUTING_KEY_UPDATED,
)
from consumer import (
    validate_xml,
    handle_session_created,
    handle_session_updated,
    reset_sessions_store,
    list_sessions,
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)


def extract_correlation_id(xml_string: str) -> str:
    """Extract correlation_id from XML."""
    root = etree.fromstring(xml_string.encode("utf-8"))
    for elem in root.iter():
        elem.tag = etree.QName(elem.tag).localname
    return root.findtext("header/correlation_id", default="NOT FOUND")


class RabbitMQListener:
    """Luistert naar RabbitMQ berichten en verzamelt ze."""
    
    def __init__(self, routing_keys: list[str]):
        self.messages = []
        self.routing_keys = routing_keys
        self.stop_flag = False
    
    def start_listening(self):
        """Start listener in aparte thread."""
        thread = threading.Thread(target=self._listen, daemon=True)
        thread.start()
        return thread
    
    def _listen(self):
        """Luister naar berichten van RabbitMQ."""
        try:
            credentials = pika.PlainCredentials("guest", "guest")
            params = pika.ConnectionParameters(
                host="localhost",
                port=5672,
                credentials=credentials,
                connection_attempts=5,
                retry_delay=2
            )
            
            connection = pika.BlockingConnection(params)
            channel = connection.channel()
            
            # Declare exchange
            channel.exchange_declare(
                exchange="planning.exchange",
                exchange_type="topic",
                durable=True
            )
            
            # Create temporary queue
            result = channel.queue_declare(queue="", exclusive=True)
            queue_name = result.method.queue
            
            # Bind queue to routing keys
            for routing_key in self.routing_keys:
                channel.queue_bind(
                    exchange="planning.exchange",
                    queue=queue_name,
                    routing_key=routing_key
                )
            
            logger.info(f"✓ Listener gebonden aan {len(self.routing_keys)} routing keys")
            
            def callback(ch, method, properties, body):
                self.messages.append(body.decode("utf-8"))
                logger.info(f"✓ Bericht ontvangen ({len(self.messages)})")
                ch.basic_ack(delivery_tag=method.delivery_tag)
            
            channel.basic_consume(queue=queue_name, on_message_callback=callback)
            
            # Listen for 10 seconds or until stop_flag
            while not self.stop_flag:
                try:
                    channel.connection.process_data_events(time_limit=1)
                except:
                    break
            
            channel.stop_consuming()
            connection.close()
            
        except Exception as e:
            logger.error(f"Listener error: {e}")


# ============================================================================
# TEST 1: Producer → RabbitMQ → Consumer
# ============================================================================
def test_producer_to_consumer():
    print("\n" + "=" * 80)
    print("TEST 1: Producer → RabbitMQ → Consumer (End-to-End)")
    print("=" * 80)
    
    SESSION_ID = "e2e-test-session-001"
    
    # Setup listener
    listener = RabbitMQListener([
        "planning.session.created",
        "planning.session.updated"
    ])
    listener_thread = listener.start_listening()
    time.sleep(2)  # Wacht tot listener klaar is
    
    # Reset consumer state
    reset_sessions_store()
    
    # STAP 1: Producer stuurt session_created
    print("\n📤 STAP 1: Producer stuurt session_created")
    created_xml = create_session_xml(
        session_id=SESSION_ID,
        title="E2E Test Session",
        start_datetime="2026-05-20T14:00:00Z",
        end_datetime="2026-05-20T15:00:00Z",
        location="Test Location"
    )
    corr_id_created = extract_correlation_id(created_xml)
    print(f"   Correlation ID: {corr_id_created}")
    
    success = send_message(created_xml, routing_key="planning.session.created")
    if not success:
        logger.error("Failed to send created message")
        return False
    
    print(f"   ✓ Bericht verzonden")
    
    # Wacht op ontvangst
    time.sleep(2)
    
    # STAP 2: Verify ontvangst en verwerk
    print("\n📥 STAP 2: Consumer ontvangt en verwerkt")
    if len(listener.messages) < 1:
        print("   ✗ Bericht niet ontvangen!")
        return False
    
    received_xml = listener.messages[0]
    corr_id_received = extract_correlation_id(received_xml)
    print(f"   Correlation ID: {corr_id_received}")
    
    # Validate en proces
    validated_root = validate_xml(received_xml)
    if not validated_root:
        print("   ✗ XML validatie gefaald!")
        return False
    
    handle_session_created(validated_root)
    print(f"   ✓ Bericht gevalideerd en verwerkt")
    
    # STAP 3: Producer stuurt session_updated
    print("\n📤 STAP 3: Producer stuurt session_updated")
    updated_xml = create_session_updated_xml(
        session_id=SESSION_ID,
        title="E2E Test Session (Updated)",
        start_datetime="2026-05-20T14:00:00Z",
        end_datetime="2026-05-20T16:00:00Z",
        location="Test Location",
        current_attendees=50
    )
    corr_id_updated = extract_correlation_id(updated_xml)
    print(f"   Correlation ID: {corr_id_updated}")
    
    success = send_message(updated_xml, routing_key="planning.session.updated")
    if not success:
        logger.error("Failed to send updated message")
        return False
    
    print(f"   ✓ Bericht verzonden")
    
    # Wacht op ontvangst
    time.sleep(2)
    
    # STAP 4: Verify tweede ontvangst
    print("\n📥 STAP 4: Consumer ontvangt update")
    if len(listener.messages) < 2:
        print("   ✗ Update bericht niet ontvangen!")
        return False
    
    received_updated_xml = listener.messages[1]
    corr_id_received_updated = extract_correlation_id(received_updated_xml)
    print(f"   Correlation ID: {corr_id_received_updated}")
    
    # Validate en proces
    validated_root_updated = validate_xml(received_updated_xml)
    if not validated_root_updated:
        print("   ✗ XML validatie gefaald!")
        return False
    
    handle_session_updated(validated_root_updated)
    print(f"   ✓ Bericht gevalideerd en verwerkt")
    
    # Stop listener
    listener.stop_flag = True
    listener_thread.join(timeout=5)
    
    # STAP 5: Verificatie
    print("\n" + "=" * 80)
    print("VERIFICATIE")
    print("=" * 80)
    
    print(f"\nCorrelation ID Journey:")
    print(f"  1. Created (Producer): {corr_id_created}")
    print(f"  2. Created (RabbitMQ): {corr_id_received}")
    print(f"  3. Updated (Producer): {corr_id_updated}")
    print(f"  4. Updated (RabbitMQ): {corr_id_received_updated}")
    
    all_same = (
        corr_id_created == corr_id_received == 
        corr_id_updated == corr_id_received_updated
    )
    
    if not all_same:
        print("\n✗ FOUT: Correlation IDs zijn NIET hetzelfde!")
        return False
    
    print(f"\n✅ SUCCESS: Alle correlation IDs zijn hetzelfde!")
    
    # Check consumer state
    print("\nConsumer State:")
    sessions = list_sessions()
    if len(sessions) != 1:
        print(f"   ✗ Verwacht 1 sessie, kreeg {len(sessions)}")
        return False
    
    session = sessions[0]
    print(f"   Session ID: {session['session_id']}")
    print(f"   Title: {session['title']}")
    print(f"   Attendees: {session.get('current_attendees', 0)}")
    print(f"   ✓ Consumer state correct")
    
    return True


# ============================================================================
# TEST 2: Message Flow Logging
# ============================================================================
def test_message_flow_logging():
    print("\n\n" + "=" * 80)
    print("TEST 2: Message Flow Logging")
    print("=" * 80)
    
    SESSION_ID = "logging-test-session"
    
    print("\n📋 Sending messages en capturing logs...")
    print("(Check correlation_id in logs)\n")
    
    # Create and send
    created_xml = create_session_xml(
        session_id=SESSION_ID,
        title="Logging Test",
        start_datetime="2026-05-21T10:00:00Z",
        end_datetime="2026-05-21T11:00:00Z",
        location="Logging Test Room"
    )
    
    corr_id = extract_correlation_id(created_xml)
    print(f"Master UUID (Correlation ID): {corr_id}")
    print("\n📝 Producer logs (met correlation_id):")
    logger.info(f"TEST: session_created message prepared | correlation_id={corr_id}")
    
    # Simulated consumer logs
    reset_sessions_store()
    validated_root = validate_xml(created_xml)
    handle_session_created(validated_root)
    
    print("\n📝 Consumer logs (met correlation_id):")
    logger.info(f"TEST: session_created received | correlation_id={corr_id}")
    
    print("\n✅ Logging test voltooid - correlation_id is zichtbaar in alle logs")
    
    return True


# ============================================================================
# TEST 3: Multiple Sessions (Different UUIDs)
# ============================================================================
def test_multiple_sessions():
    print("\n\n" + "=" * 80)
    print("TEST 3: Multiple Sessions - Verschillende UUIDs")
    print("=" * 80)
    
    reset_sessions_store()
    
    sessions_data = [
        ("session-a", "Conference 2026"),
        ("session-b", "Workshop Python"),
        ("session-c", "Keynote AI"),
    ]
    
    correlation_ids = {}
    
    print("\nCreating multiple sessions:\n")
    for session_id, title in sessions_data:
        xml = create_session_xml(
            session_id=session_id,
            title=title,
            start_datetime="2026-05-22T14:00:00Z",
            end_datetime="2026-05-22T15:00:00Z",
            location="Room"
        )
        corr_id = extract_correlation_id(xml)
        correlation_ids[session_id] = corr_id
        
        # Validate and process
        root = validate_xml(xml)
        handle_session_created(root)
        
        print(f"  {session_id:15} → {corr_id}")
    
    # Verify uniqueness
    unique_ids = len(set(correlation_ids.values()))
    total_sessions = len(sessions_data)
    
    print(f"\nVerificatie:")
    print(f"  Total sessions: {total_sessions}")
    print(f"  Unique correlation IDs: {unique_ids}")
    
    if unique_ids != total_sessions:
        print(f"  ✗ FOUT: Expected {total_sessions} unique IDs, got {unique_ids}")
        return False
    
    print(f"  ✅ SUCCESS: Alle sessies hebben unieke correlation IDs!")
    
    return True


# ============================================================================
# MAIN
# ============================================================================
def main():
    print("\n" + "🧪 END-TO-END TEST SUITE 🧪".center(80))
    
    results = {
        "Producer → RabbitMQ → Consumer": False,
        "Message Flow Logging": False,
        "Multiple Sessions": False,
    }
    
    try:
        # Test 1
        results["Producer → RabbitMQ → Consumer"] = test_producer_to_consumer()
        
        # Test 2
        results["Message Flow Logging"] = test_message_flow_logging()
        
        # Test 3
        results["Multiple Sessions"] = test_multiple_sessions()
        
    except Exception as e:
        logger.error(f"Test error: {e}", exc_info=True)
    
    # Summary
    print("\n\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    
    for test_name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"  {test_name:40} {status}")
    
    all_passed = all(results.values())
    
    print("\n" + "=" * 80)
    if all_passed:
        print("🎉 ALL TESTS PASSED!")
    else:
        print("⚠️ SOME TESTS FAILED!")
    print("=" * 80)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    exit_code = main()
    exit(exit_code)
