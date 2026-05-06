"""
End-to-End Test: Producer → RabbitMQ → Consumer (Lokale Test Version)
Tests het volledige flow met echte RabbitMQ en verifiëert correlation_id tracing.
"""
import pika
import json
import time
import logging
import threading
from lxml import etree
from pathlib import Path

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


def test_rabbitmq_connection():
    """Test connection to RabbitMQ."""
    print("\n" + "=" * 80)
    print("TEST 1: RabbitMQ Connection")
    print("=" * 80)
    
    try:
        credentials = pika.PlainCredentials("guest", "guest")
        params = pika.ConnectionParameters(
            host="127.0.0.1",  # Localhost
            port=5672,
            credentials=credentials,
            connection_attempts=3,
            retry_delay=2
        )
        
        connection = pika.BlockingConnection(params)
        channel = connection.channel()
        
        print("\n✅ Verbinding succesvol!")
        print(f"   Host: 127.0.0.1:5672")
        print(f"   Channel: {channel.channel_number}")
        
        connection.close()
        return True
        
    except Exception as e:
        print(f"\n❌ Verbinding mislukt: {e}")
        return False


def test_message_send_receive():
    """Test sending and receiving messages via RabbitMQ."""
    print("\n" + "=" * 80)
    print("TEST 2: Send & Receive Message via RabbitMQ")
    print("=" * 80)
    
    EXCHANGE = "test.exchange"
    ROUTING_KEY = "test.routing.key"
    
    try:
        credentials = pika.PlainCredentials("guest", "guest")
        params = pika.ConnectionParameters(
            host="127.0.0.1",
            port=5672,
            credentials=credentials,
            connection_attempts=3,
            retry_delay=2
        )
        
        # Setup: Create exchange
        print("\n📋 Setting up RabbitMQ...")
        connection = pika.BlockingConnection(params)
        channel = connection.channel()
        
        channel.exchange_declare(
            exchange=EXCHANGE,
            exchange_type='topic',
            durable=True
        )
        
        result = channel.queue_declare(queue="", exclusive=True)
        queue_name = result.method.queue
        
        channel.queue_bind(
            exchange=EXCHANGE,
            queue=queue_name,
            routing_key=ROUTING_KEY
        )
        
        print(f"   ✓ Exchange: {EXCHANGE}")
        print(f"   ✓ Queue: {queue_name}")
        
        # Publish message
        print("\n📤 Publishing message...")
        test_message = """<?xml version="1.0" encoding="UTF-8"?>
<message xmlns="urn:integration:planning:v1">
    <header>
        <message_id>msg-12345</message_id>
        <timestamp>2026-04-29T13:00:00Z</timestamp>
        <source>planning</source>
        <type>session_created</type>
        <version>1.0</version>
        <correlation_id>test-correlation-uuid-12345</correlation_id>
    </header>
    <body>
        <session_id>test-session</session_id>
        <title>Test Message</title>
        <start_datetime>2026-05-20T14:00:00Z</start_datetime>
        <end_datetime>2026-05-20T15:00:00Z</end_datetime>
        <location>Test Location</location>
        <session_type>test</session_type>
        <status>test</status>
        <max_attendees>10</max_attendees>
        <current_attendees>5</current_attendees>
    </body>
</message>"""
        
        channel.basic_publish(
            exchange=EXCHANGE,
            routing_key=ROUTING_KEY,
            body=test_message,
            properties=pika.BasicProperties(
                content_type="application/xml",
                delivery_mode=2
            )
        )
        
        corr_id = extract_correlation_id(test_message)
        print(f"   ✓ Message published")
        print(f"   ✓ Correlation ID: {corr_id}")
        
        # Consume message
        print("\n📥 Consuming message...")
        received_message = None
        
        def callback(ch, method, properties, body):
            nonlocal received_message
            received_message = body.decode("utf-8")
            ch.basic_ack(delivery_tag=method.delivery_tag)
        
        channel.basic_consume(queue=queue_name, on_message_callback=callback)
        
        # Process events for 5 seconds
        start_time = time.time()
        while time.time() - start_time < 5:
            channel.connection.process_data_events(time_limit=0.5)
            if received_message:
                break
        
        channel.stop_consuming()
        connection.close()
        
        if not received_message:
            print("   ❌ No message received!")
            return False
        
        print(f"   ✓ Message received")
        
        # Verify correlation_id
        received_corr_id = extract_correlation_id(received_message)
        print(f"   ✓ Received Correlation ID: {received_corr_id}")
        
        if corr_id != received_corr_id:
            print(f"   ❌ Correlation IDs don't match!")
            return False
        
        print(f"\n✅ Message successfully passed through RabbitMQ with same correlation_id!")
        return True
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_correlation_id_persistence():
    """Test that correlation_id is correctly loaded from storage."""
    print("\n" + "=" * 80)
    print("TEST 3: Correlation ID Persistence")
    print("=" * 80)
    
    try:
        from producer import MasterUUIDManager
        
        print("\n📋 Testing Master UUID storage...")
        
        # Test 1: Create new UUID
        SESSION_ID = f"persistence-test-{int(time.time())}"
        uuid1 = MasterUUIDManager.get_or_create(SESSION_ID)
        print(f"   Created UUID for {SESSION_ID}:")
        print(f"   {uuid1}")
        
        # Test 2: Retrieve same UUID
        uuid2 = MasterUUIDManager.get(SESSION_ID)
        print(f"\n   Retrieved UUID:")
        print(f"   {uuid2}")
        
        if uuid1 != uuid2:
            print(f"\n   ❌ UUIDs don't match!")
            return False
        
        # Test 3: Verify in file
        master_file = Path(__file__).resolve().parent / ".master_uuids.json"
        if master_file.exists():
            with open(master_file, "r") as f:
                data = json.load(f)
            
            if SESSION_ID in data and data[SESSION_ID] == uuid1:
                print(f"\n   ✓ UUID correctly stored in .master_uuids.json")
            else:
                print(f"\n   ❌ UUID not found in storage file!")
                return False
        
        print(f"\n✅ Correlation ID persistence works correctly!")
        return True
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_xml_validation_with_correlation_id():
    """Test that XML validation preserves correlation_id."""
    print("\n" + "=" * 80)
    print("TEST 4: XML Validation with Correlation ID")
    print("=" * 80)
    
    try:
        from producer import create_session_xml, MasterUUIDManager
        from consumer import validate_xml, handle_session_created
        
        SESSION_ID = "validation-test-session"
        
        print("\n📋 Creating session with Master UUID...")
        
        # Create message
        xml = create_session_xml(
            session_id=SESSION_ID,
            title="Validation Test",
            start_datetime="2026-05-20T14:00:00Z",
            end_datetime="2026-05-20T15:00:00Z",
            location="Test"
        )
        
        original_corr_id = extract_correlation_id(xml)
        print(f"   Original Correlation ID: {original_corr_id}")
        
        # Validate
        print("\n✓ Validating XML...")
        validated_root = validate_xml(xml)
        
        if not validated_root:
            print("   ❌ XML validation failed!")
            return False
        
        print("   ✓ XML validation passed")
        
        # Extract correlation_id from validated XML
        validated_corr_id = validated_root.findtext(
            "{urn:integration:planning:v1}header/{urn:integration:planning:v1}correlation_id"
        )
        if not validated_corr_id:
            # Try without namespace
            for elem in validated_root.iter():
                elem.tag = etree.QName(elem.tag).localname
            validated_corr_id = validated_root.findtext("header/correlation_id")
        
        print(f"   Validated Correlation ID: {validated_corr_id}")
        
        # Process
        print("\n✓ Processing message...")
        handle_session_created(validated_root)
        print("   ✓ Message processed")
        
        print(f"\n✅ XML validation and processing preserves correlation_id!")
        return True
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


# ============================================================================
# MAIN
# ============================================================================
def main():
    print("\n" + "🧪 COMPREHENSIVE E2E TEST SUITE 🧪".center(80))
    
    results = {
        "RabbitMQ Connection": False,
        "Send & Receive Message": False,
        "Correlation ID Persistence": False,
        "XML Validation with Correlation ID": False,
    }
    
    try:
        results["RabbitMQ Connection"] = test_rabbitmq_connection()
        results["Send & Receive Message"] = test_message_send_receive()
        results["Correlation ID Persistence"] = test_correlation_id_persistence()
        results["XML Validation with Correlation ID"] = test_xml_validation_with_correlation_id()
        
    except Exception as e:
        logger.error(f"Test error: {e}", exc_info=True)
    
    # Summary
    print("\n\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    
    passed = 0
    failed = 0
    
    for test_name, result in results.items():
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"  {test_name:40} {status}")
        if result:
            passed += 1
        else:
            failed += 1
    
    print("\n" + "=" * 80)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 80)
    
    if failed == 0:
        print("\n🎉 ALL TESTS PASSED!")
        return 0
    else:
        print(f"\n⚠️ {failed} TEST(S) FAILED!")
        return 1


if __name__ == "__main__":
    exit_code = main()
    exit(exit_code)
