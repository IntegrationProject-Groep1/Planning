"""
Database seeder for Planning Service.
Creates professional demo sessions and publishes them via RabbitMQ.
The consumer will automatically store them in the database.

Usage:
    python seeder.py
    
Or in Docker:
    docker compose exec planning-service python seeder.py
"""

import pika
import os
import logging
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone

from xml_handlers import build_session_created_xml

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# RabbitMQ connection settings
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "guest")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "guest")
RABBITMQ_VHOST = os.getenv("RABBITMQ_VHOST", "/")

# Exchange configuration
PLANNING_EXCHANGE = "planning.exchange"
ROUTING_KEY = "planning.session.created"


def _get_connection():
    """Create a RabbitMQ connection."""
    try:
        credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
        params = pika.ConnectionParameters(
            host=RABBITMQ_HOST,
            port=RABBITMQ_PORT,
            virtual_host=RABBITMQ_VHOST,
            credentials=credentials,
            connection_attempts=3,
            retry_delay=2,
        )
        return pika.BlockingConnection(params)
    except pika.exceptions.AMQPConnectionError as e:
        logger.error("Failed to connect to RabbitMQ: %s", e)
        raise


def _publish_session(session_data: dict) -> bool:
    """Publish a single session via RabbitMQ."""
    try:
        connection = _get_connection()
        channel = connection.channel()

        # Declare exchange
        channel.exchange_declare(
            exchange=PLANNING_EXCHANGE,
            exchange_type="topic",
            durable=True,
        )

        # Build XML message
        xml_message = build_session_created_xml(
            session_id=session_data["session_id"],
            title=session_data["title"],
            start_datetime=session_data["start_datetime"],
            end_datetime=session_data["end_datetime"],
            location=session_data.get("location", ""),
            session_type=session_data.get("session_type", "keynote"),
            status=session_data.get("status", "published"),
            max_attendees=session_data.get("max_attendees", 0),
            current_attendees=session_data.get("current_attendees", 0),
        )

        # Publish message
        channel.basic_publish(
            exchange=PLANNING_EXCHANGE,
            routing_key=ROUTING_KEY,
            body=xml_message.encode() if isinstance(xml_message, str) else xml_message,
            properties=pika.BasicProperties(
                content_type="application/xml",
                delivery_mode=2,  # Persistent
            ),
        )

        connection.close()
        logger.info("✓ Published: %s (%s)", session_data["title"], session_data["session_id"])
        return True

    except Exception as e:
        logger.error("✗ Failed to publish %s: %s", session_data["session_id"], e, exc_info=True)
        return False


def create_seed_sessions():
    """Define all seed sessions (8 total - 2 existing + 6 new)."""
    base_time = datetime.now(timezone.utc)
    
    sessions = [
        # Existing 2 sessions (placeholders - adjust as needed)
        {
            "session_id": "sess-demo-001",
            "title": "Keynote: Future of Enterprise Integration",
            "start_datetime": (base_time + timedelta(days=1)).isoformat(),
            "end_datetime": (base_time + timedelta(days=1, hours=1)).isoformat(),
            "location": "Main Hall",
            "session_type": "keynote",
            "status": "published",
            "max_attendees": 200,
            "current_attendees": 145,
        },
        {
            "session_id": "sess-demo-002",
            "title": "Workshop: Microservices Architecture",
            "start_datetime": (base_time + timedelta(days=2)).isoformat(),
            "end_datetime": (base_time + timedelta(days=2, hours=2)).isoformat(),
            "location": "Workshop Room A",
            "session_type": "workshop",
            "status": "published",
            "max_attendees": 50,
            "current_attendees": 42,
        },
        
        # 6 new sessions for demo
        {
            "session_id": "sess-demo-003",
            "title": "Panel Discussion: Cloud Strategy",
            "start_datetime": (base_time + timedelta(days=3)).isoformat(),
            "end_datetime": (base_time + timedelta(days=3, hours=1, minutes=30)).isoformat(),
            "location": "Conference Room B",
            "session_type": "panel",
            "status": "published",
            "max_attendees": 100,
            "current_attendees": 78,
        },
        {
            "session_id": "sess-demo-004",
            "title": "Networking Lunch & Learn",
            "start_datetime": (base_time + timedelta(days=4, hours=12)).isoformat(),
            "end_datetime": (base_time + timedelta(days=4, hours=13)).isoformat(),
            "location": "Cafeteria",
            "session_type": "networking",
            "status": "published",
            "max_attendees": 150,
            "current_attendees": 120,
        },
        {
            "session_id": "sess-demo-005",
            "title": "Technical Deep Dive: API Design",
            "start_datetime": (base_time + timedelta(days=5)).isoformat(),
            "end_datetime": (base_time + timedelta(days=5, hours=2)).isoformat(),
            "location": "Tech Lab",
            "session_type": "workshop",
            "status": "published",
            "max_attendees": 60,
            "current_attendees": 54,
        },
        {
            "session_id": "sess-demo-006",
            "title": "Product Showcase: Next Generation Platform",
            "start_datetime": (base_time + timedelta(days=6)).isoformat(),
            "end_datetime": (base_time + timedelta(days=6, hours=1)).isoformat(),
            "location": "Demo Theater",
            "session_type": "presentation",
            "status": "published",
            "max_attendees": 300,
            "current_attendees": 267,
        },
        {
            "session_id": "sess-demo-007",
            "title": "Open Forum: Feedback & Q&A",
            "start_datetime": (base_time + timedelta(days=7)).isoformat(),
            "end_datetime": (base_time + timedelta(days=7, hours=1, minutes=30)).isoformat(),
            "location": "Main Hall",
            "session_type": "forum",
            "status": "published",
            "max_attendees": 250,
            "current_attendees": 189,
        },
        {
            "session_id": "sess-demo-008",
            "title": "Closing Remarks & Awards Ceremony",
            "start_datetime": (base_time + timedelta(days=8)).isoformat(),
            "end_datetime": (base_time + timedelta(days=8, hours=2)).isoformat(),
            "location": "Main Hall",
            "session_type": "ceremony",
            "status": "published",
            "max_attendees": 500,
            "current_attendees": 450,
        },
    ]
    
    return sessions


def main():
    """Run the seeder."""
    logger.info("=" * 70)
    logger.info("Planning Service Seeder - Creating Demo Sessions")
    logger.info("=" * 70)
    
    sessions = create_seed_sessions()
    successful = 0
    failed = 0
    
    for session in sessions:
        if _publish_session(session):
            successful += 1
        else:
            failed += 1
    
    logger.info("=" * 70)
    logger.info("Seeding Complete!")
    logger.info("  ✓ Successful: %d", successful)
    logger.info("  ✗ Failed: %d", failed)
    logger.info("=" * 70)
    
    if failed == 0:
        logger.info("All sessions will be processed by the consumer and stored in the database.")
        return 0
    else:
        return 1


if __name__ == "__main__":
    exit(main())
