import pika
import uuid
from datetime import datetime, timezone
from dotenv import load_dotenv
import os

load_dotenv()

credentials = pika.PlainCredentials(os.getenv("RABBITMQ_USER"), os.getenv("RABBITMQ_PASS"))
params = pika.ConnectionParameters(
    host=os.getenv("RABBITMQ_HOST"),
    port=int(os.getenv("RABBITMQ_PORT", "5672")),
    virtual_host=os.getenv("RABBITMQ_VHOST", "/"),
    credentials=credentials,
)

xml = f"""<message xmlns="urn:integration:planning:v1">
    <header>
        <message_id>{uuid.uuid4()}</message_id>
        <timestamp>{datetime.now(timezone.utc).isoformat()}</timestamp>
        <source>test</source>
        <type>calendar.invite</type>
    </header>
    <body>
        <session_id>sess-test-001</session_id>
        <title>Test sessie</title>
        <start_datetime>2026-05-15T14:00:00Z</start_datetime>
        <end_datetime>2026-05-15T15:00:00Z</end_datetime>
        <location>online</location>
    </body>
</message>"""

connection = pika.BlockingConnection(params)
channel = connection.channel()
channel.exchange_declare(exchange="calendar.exchange", exchange_type="topic", durable=True)
channel.basic_publish(exchange="calendar.exchange", routing_key="calendar.invite", body=xml.encode())
connection.close()
print("Test message sent!")
