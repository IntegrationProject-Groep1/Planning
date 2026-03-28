import pika
import time
import uuid
from datetime import datetime, timezone
from dotenv import load_dotenv
import os

load_dotenv()

def get_connection():
    credentials = pika.PlainCredentials(
        os.getenv("RABBITMQ_USER"),
        os.getenv("RABBITMQ_PASS")
    )
    parameters = pika.ConnectionParameters(
        host=os.getenv("RABBITMQ_HOST"),
        port=int(os.getenv("RABBITMQ_PORT")),
        credentials=credentials
    )
    return pika.BlockingConnection(parameters)

def build_heartbeat_xml():
    now = datetime.now(timezone.utc).isoformat()
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<message xmlns="urn:integration:heartbeat:v1">
    <header>
        <message_id>{uuid.uuid4()}</message_id>
        <timestamp>{now}</timestamp>
        <source>planning</source>
        <type>heartbeat</type>
    </header>
    <body>
        <status>online</status>
        <outlook_api_connected>true</outlook_api_connected>
        <rabbitmq_connected>true</rabbitmq_connected>
        <uptime>0</uptime>
    </body>
</message>"""

def start_heartbeat():
    connection = get_connection()
    channel = connection.channel()
    channel.exchange_declare(
        exchange="heartbeat",
        exchange_type="topic",
        durable=True
    )
    print("Heartbeat gestart...")
    while True:
        xml = build_heartbeat_xml()
        channel.basic_publish(
            exchange="heartbeat",
            routing_key="heartbeat.planning",
            body=xml.encode("utf-8")
        )
        print(f"Heartbeat verstuurd: {datetime.now()}")
        time.sleep(1)

if __name__ == "__main__":
    start_heartbeat()
