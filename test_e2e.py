"""
End-to-end test: create session + user + calendar invite + ICS feed
Run: python test_e2e.py
"""
import pika
import uuid
import time
import threading
import urllib.request
import json
from datetime import datetime, timezone

# ── Config ────────────────────────────────────────────────────────────────────
HOST     = "integrationproject-2526s2-dag01.westeurope.cloudapp.azure.com"
AMQP_PORT = 30000
MGMT_PORT = 30001
USER     = "planning_rabbitmq"
PASS     = "IsPI22"
ICS_BASE = "http://{}:30050".format(HOST)

SESSION_ID = str(uuid.uuid4())
USER_ID    = "test-user-{}".format(uuid.uuid4().hex[:6])
NOW        = datetime.now(timezone.utc).isoformat()

# ── Helpers ───────────────────────────────────────────────────────────────────
def make_connection():
    creds  = pika.PlainCredentials(USER, PASS)
    params = pika.ConnectionParameters(host=HOST, port=AMQP_PORT,
                                       virtual_host="/", credentials=creds,
                                       connection_attempts=2, retry_delay=1)
    return pika.BlockingConnection(params)

def publish(exchange, routing_key, xml):
    conn = make_connection()
    ch   = conn.channel()
    ch.basic_publish(exchange=exchange, routing_key=routing_key, body=xml,
                     properties=pika.BasicProperties(content_type="application/xml", delivery_mode=2))
    conn.close()

def mgmt_get(path):
    import base64
    url = "http://{}:{}/api{}".format(HOST, MGMT_PORT, path)
    req = urllib.request.Request(url)
    req.add_header("Authorization", "Basic " + base64.b64encode("{}:{}".format(USER, PASS).encode()).decode())
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())

def sep(title):
    print("\n" + "─" * 60)
    print("  " + title)
    print("─" * 60)

# ── Step 1: Créer la session ──────────────────────────────────────────────────
sep("STEP 1 — Publish session_create_request")
session_xml = """<message>
  <header>
    <message_id>{mid}</message_id>
    <timestamp>{ts}</timestamp>
    <source>test_e2e</source>
    <type>session_create_request</type>
    <version>2.0</version>
  </header>
  <body>
    <session_id>{sid}</session_id>
    <title>E2E Test Session</title>
    <start_datetime>2026-05-20T10:00:00.000Z</start_datetime>
    <end_datetime>2026-05-20T11:00:00.000Z</end_datetime>
    <location>Aula B - Campus Jette</location>
    <session_type>workshop</session_type>
    <max_attendees>30</max_attendees>
  </body>
</message>""".format(mid=str(uuid.uuid4()), ts=NOW, sid=SESSION_ID)

publish("planning.exchange", "frontend.to.planning.session.create", session_xml)
print("Session ID : {}".format(SESSION_ID))
print("Routing key: frontend.to.planning.session.create")
print("Status     : published ✓")

# ── Step 2: Attendre le traitement ────────────────────────────────────────────
sep("STEP 2 — Wait for consumer to process (3s)...")
time.sleep(3)

# ── Step 3: Vérifier que la session est dans la queue events ─────────────────
sep("STEP 3 — Check planning.session.events queue")
try:
    queues = mgmt_get("/queues")
    for q in queues:
        if "planning" in q["name"]:
            status = "✓ clear" if q.get("messages", 0) == 0 else "⚠ {} pending".format(q["messages"])
            print("  {:<35} consumers: {}  {}".format(
                q["name"], q.get("consumers", 0), status))
except Exception as e:
    print("  Could not check management API: {}".format(e))

# ── Step 4: Créer le calendar invite pour le user (sans Outlook token) ────────
sep("STEP 4 — Publish calendar_invite for user: {}".format(USER_ID))
invite_xml = """<message>
  <header>
    <message_id>{mid}</message_id>
    <timestamp>{ts}</timestamp>
    <source>test_e2e</source>
    <type>calendar_invite</type>
    <version>2.0</version>
  </header>
  <body>
    <session_id>{sid}</session_id>
    <title>E2E Test Session</title>
    <start_datetime>2026-05-20T10:00:00.000Z</start_datetime>
    <end_datetime>2026-05-20T11:00:00.000Z</end_datetime>
    <location>Aula B - Campus Jette</location>
    <user_id>{uid}</user_id>
    <attendee_email>{uid}@test.be</attendee_email>
  </body>
</message>""".format(mid=str(uuid.uuid4()), ts=NOW, sid=SESSION_ID, uid=USER_ID)

publish("calendar.exchange", "frontend.to.planning.calendar.invite", invite_xml)
print("User ID    : {}".format(USER_ID))
print("Status     : published ✓ (no Outlook token → ICS feed will be created)")

# ── Step 5: Attendre + capturer la réponse depuis planning.session.events ─────
sep("STEP 5 — Listen for confirmation message (5s timeout)")

confirmed_xml = None
ics_url       = None

def consume_reply():
    global confirmed_xml, ics_url
    try:
        conn = make_connection()
        ch   = conn.channel()
        # Temporary exclusive queue
        result  = ch.queue_declare(queue="", exclusive=True, auto_delete=True)
        tmp_q   = result.method.queue
        ch.queue_bind(exchange="planning.exchange", queue=tmp_q,
                      routing_key="planning.to.frontend.session.created")
        ch.queue_bind(exchange="planning.exchange", queue=tmp_q,
                      routing_key="planning.to.frontend.#")

        def on_msg(ch, method, props, body):
            global confirmed_xml, ics_url
            confirmed_xml = body.decode()
            # Try to extract ICS URL
            try:
                import re
                m = re.search(r"<ics_url>(.*?)</ics_url>", confirmed_xml)
                if m:
                    ics_url = m.group(1)
            except Exception:
                pass
            ch.stop_consuming()

        ch.basic_consume(queue=tmp_q, on_message_callback=on_msg, auto_ack=True)
        conn.call_later(5, ch.stop_consuming)
        ch.start_consuming()
        conn.close()
    except Exception as e:
        print("  Listener error: {}".format(e))

t = threading.Thread(target=consume_reply)
t.start()
time.sleep(5)
t.join(timeout=6)

if confirmed_xml:
    print("Received confirmation message ✓")
    print(confirmed_xml[:400])
else:
    print("No reply captured (may already have been consumed by another consumer)")

# ── Step 6: Tenter de récupérer l'ICS feed ───────────────────────────────────
sep("STEP 6 — Fetch ICS feed")

if ics_url:
    print("ICS URL from message: {}".format(ics_url))
    try:
        req = urllib.request.Request(ics_url)
        with urllib.request.urlopen(req, timeout=5) as r:
            content = r.read().decode()
            if "BEGIN:VCALENDAR" in content:
                print("ICS feed ✓ — content preview:")
                print(content[:500])
            else:
                print("Got response but not a valid ICS: {}".format(content[:200]))
    except Exception as e:
        print("Could not fetch ICS: {}".format(e))
else:
    # Try the planning service list endpoint
    print("No ICS URL captured from message — trying planning service API...")
    try:
        url = "{}/api/ics-feeds".format(ICS_BASE)
        with urllib.request.urlopen(url, timeout=5) as r:
            feeds = json.loads(r.read())
            for f in feeds:
                if USER_ID in str(f):
                    ics_url = "{}/ical/{}?token={}".format(ICS_BASE, f.get("user_id"), f.get("feed_token"))
                    print("ICS URL: {}".format(ics_url))
                    break
    except Exception as e:
        print("  API not reachable: {}".format(e))

    if not ics_url:
        print("  ICS URL not retrievable externally (DB not exposed).")
        print("  → Run the frontend demo and check http://localhost:8089 to see ICS feeds.")

# ── Résumé ────────────────────────────────────────────────────────────────────
sep("SUMMARY")
print("Session ID : {}".format(SESSION_ID))
print("User ID    : {}".format(USER_ID))
print("ICS URL    : {}".format(ics_url or "check frontend demo at http://localhost:8089"))
print()
print("RabbitMQ Management: http://{}:{}/".format(HOST, MGMT_PORT))
print("Planning service   : {}".format(ICS_BASE))
