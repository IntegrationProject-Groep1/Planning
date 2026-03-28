import pika
import time
import uuid
from datetime import datetime, timezone
from dotenv import load_dotenv
import os
import socket

load_dotenv()

# Timestamp de inicio del servicio
SERVICE_START_TIME = time.time()

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

def check_outlook_connection():
    """Verifica conectabilidad a Outlook API (básico)."""
    try:
        socket.gethostbyname('outlook.office365.com')
        return True
    except socket.error:
        return False

def get_current_uptime():
    """Retorna uptime en segundos desde que inició el servicio."""
    return int(time.time() - SERVICE_START_TIME)

def build_heartbeat_xml():
    now = datetime.now(timezone.utc).isoformat()
    uptime = get_current_uptime()
    outlook_ok = check_outlook_connection()
    
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<message xmlns="urn:integration:heartbeat:v1">
    <header>
        <message_id>{uuid.uuid4()}</message_id>
        <timestamp>{now}</timestamp>
        <source>planning</source>
        <type>heartbeat</type>
        <hostname>{socket.gethostname()}</hostname>
    </header>
    <body>
        <status>online</status>
        <outlook_api_connected>{str(outlook_ok).lower()}</outlook_api_connected>
        <rabbitmq_connected>true</rabbitmq_connected>
        <uptime>{uptime}</uptime>
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
    print("Heartbeat started...")
    while True:
        xml = build_heartbeat_xml()
        channel.basic_publish(
            exchange="heartbeat",
            routing_key="heartbeat.planning",
            body=xml.encode("utf-8")
        )
        print(f"Heartbeat sent: {datetime.now()}")
        time.sleep(1)

if __name__ == "__main__":
    start_heartbeat()
