"""
Planning Service — Frontend Demo
Simulates the frontend: create/edit sessions, join sessions, login with Microsoft.
Run: python frontend_demo.py
Then open: http://localhost:8089

Microsoft Login:
  - Uses the PlanningSync Azure app (AZURE_CLIENT_ID).
  - Add http://localhost:8089 as a redirect URI in the Azure portal (SPA type).
  - Scopes: User.Read + Calendars.ReadWrite
  - When a logged-in user joins a session, the event is added to their personal
    Outlook calendar directly from the browser via Graph API.
  If AZURE_CLIENT_ID is not set, demo login mode is used instead.
"""

import json
import logging
import os
import pathlib
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

import requests as _requests

import pika
import psycopg2
from psycopg2.extras import DictCursor
from dotenv import load_dotenv

from xml_handlers import build_calendar_invite_xml, build_session_updated_xml

load_dotenv()

logger = logging.getLogger(__name__)

_STATIC_DIR = pathlib.Path(__file__).parent / "static"
_MSAL_FILE = _STATIC_DIR / "msal-browser.min.js"
_MSAL_URLS = [
    "https://alcdn.msauth.net/browser/2.38.3/js/msal-browser.min.js",
    "https://unpkg.com/@azure/msal-browser@2.38.3/lib/msal-browser.min.js",
    "https://cdn.jsdelivr.net/npm/@azure/msal-browser@2.38.3/lib/msal-browser.min.js",
]


def _ensure_msal() -> None:
    if _MSAL_FILE.exists():
        return
    _STATIC_DIR.mkdir(exist_ok=True)
    for url in _MSAL_URLS:
        logger.info("Downloading MSAL from %s …", url)
        try:
            r = _requests.get(url, timeout=15)
            r.raise_for_status()
            _MSAL_FILE.write_bytes(r.content)
            logger.info("MSAL saved to %s", _MSAL_FILE)
            return
        except Exception as exc:
            logger.warning("Failed (%s): %s", url, exc)
    logger.error("Could not download MSAL from any source.")

DEMO_PORT = int(os.getenv("DEMO_PORT", "8089"))
CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "")

# DB
_DB_URL = os.getenv("DATABASE_URL") or (
    "postgresql://{user}:{password}@{host}:{port}/{db}".format(
        user=os.getenv("POSTGRES_USER", "planning_user"),
        password=os.getenv("POSTGRES_PASSWORD", ""),
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5433"),
        db=os.getenv("POSTGRES_DB", "planning_db"),
    )
)

# RabbitMQ
_RABBIT = dict(
    host=os.getenv("RABBITMQ_HOST", "localhost"),
    port=int(os.getenv("RABBITMQ_PORT", "5672")),
    user=os.getenv("RABBITMQ_USER", "guest"),
    password=os.getenv("RABBITMQ_PASS", "guest"),
    vhost=os.getenv("RABBITMQ_VHOST", "/"),
)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _db_sessions() -> list[dict]:
    try:
        with psycopg2.connect(_DB_URL, cursor_factory=DictCursor, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT s.session_id, s.title, s.start_datetime, s.end_datetime,
                           s.location, s.session_type, s.status,
                           s.max_attendees, s.current_attendees,
                           COALESCE(gs.sync_status, 'not_synced') AS outlook_status
                    FROM sessions s
                    LEFT JOIN graph_sync gs ON gs.session_id = s.session_id
                    WHERE s.is_deleted = FALSE
                    ORDER BY s.start_datetime ASC
                    LIMIT 20
                    """
                )
                return [dict(r) for r in cur.fetchall()]
    except Exception as exc:
        logger.warning("DB read failed: %s", exc)
        return []


def _db_direct_insert(session_id, title, start_dt, end_dt, location) -> bool:
    """Fallback: insert directly to DB when RabbitMQ is unavailable."""
    try:
        with psycopg2.connect(_DB_URL, cursor_factory=DictCursor, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO sessions
                        (session_id, title, start_datetime, end_datetime, location,
                         session_type, status, max_attendees, current_attendees)
                    VALUES (%s, %s, %s, %s, %s, 'keynote', 'published', 0, 0)
                    ON CONFLICT (session_id) DO NOTHING
                    """,
                    (session_id, title, start_dt, end_dt, location),
                )
        return True
    except Exception as exc:
        logger.error("DB direct insert failed: %s", exc)
        return False


def _db_update_session(session_id, title, start_dt, end_dt, location) -> bool:
    """Update a session record directly in the DB (fallback when RabbitMQ is unavailable)."""
    try:
        with psycopg2.connect(_DB_URL, cursor_factory=DictCursor, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE sessions
                    SET title = %s, start_datetime = %s, end_datetime = %s, location = %s
                    WHERE session_id = %s AND is_deleted = FALSE
                    """,
                    (title, start_dt, end_dt, location, session_id),
                )
        return True
    except Exception as exc:
        logger.error("DB direct update failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# RabbitMQ publish
# ---------------------------------------------------------------------------

def _rabbit_publish(exchange: str, routing_key: str, xml: str) -> bool:
    try:
        creds = pika.PlainCredentials(_RABBIT["user"], _RABBIT["password"])
        params = pika.ConnectionParameters(
            host=_RABBIT["host"],
            port=_RABBIT["port"],
            virtual_host=_RABBIT["vhost"],
            credentials=creds,
            connection_attempts=2,
            retry_delay=1,
        )
        conn = pika.BlockingConnection(params)
        ch = conn.channel()
        ch.exchange_declare(exchange=exchange, exchange_type="topic", durable=True)
        ch.basic_publish(
            exchange=exchange,
            routing_key=routing_key,
            body=xml,
            properties=pika.BasicProperties(content_type="application/xml", delivery_mode=2),
        )
        conn.close()
        return True
    except Exception as exc:
        logger.warning("RabbitMQ publish failed: %s", exc)
        return False


def _publish_calendar_invite(session_id, title, start_dt, end_dt, location) -> tuple[bool, str]:
    """Publish a calendar.invite message. Returns (success, method)."""
    try:
        xml = build_calendar_invite_xml(
            session_id=session_id,
            title=title,
            start_datetime=start_dt,
            end_datetime=end_dt,
            location=location,
        )
        if _rabbit_publish("calendar.exchange", "calendar.invite", xml):
            return True, "rabbitmq"
    except Exception as exc:
        logger.warning("calendar.invite build/publish failed: %s", exc)

    ok = _db_direct_insert(session_id, title, start_dt, end_dt, location)
    return ok, "direct_db"


def _get_graph_event_id(session_id: str) -> str | None:
    """Return the Outlook event ID linked to a session, or None."""
    try:
        with psycopg2.connect(_DB_URL, cursor_factory=DictCursor, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT graph_event_id FROM graph_sync "
                    "WHERE session_id = %s AND sync_status = 'synced'",
                    (session_id,),
                )
                row = cur.fetchone()
                return row["graph_event_id"] if row else None
    except Exception as exc:
        logger.error("DB error fetching graph_event_id: %s", exc)
        return None


def _add_attendee_to_event(session_id: str, attendee_email: str) -> tuple[bool, str]:
    """Add an attendee to the planning Outlook event via Graph API."""
    from graph_client import GraphClient, GraphClientError
    import requests as req

    event_id = _get_graph_event_id(session_id)
    if not event_id:
        return False, "No synced Outlook event found for this session."
    try:
        client = GraphClient()
        token = client._get_token()
        from graph_client import GRAPH_BASE_URL
        url = f"{GRAPH_BASE_URL}/me/calendar/events/{event_id}"
        # Fetch current attendees first
        r = req.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=10)
        current = r.json().get("attendees", []) if r.ok else []
        # Add new attendee if not already present
        emails = {a["emailAddress"]["address"].lower() for a in current}
        if attendee_email.lower() not in emails:
            current.append({
                "emailAddress": {"address": attendee_email, "name": attendee_email},
                "type": "required",
            })
        r2 = req.patch(
            url + "?sendUpdates=all",
            json={"attendees": current},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=10,
        )
        if r2.ok:
            logger.info("Attendee %s added to event %s", attendee_email, event_id)
            return True, ""
        err = r2.json().get("error", {}).get("message", r2.text)
        return False, err
    except GraphClientError as exc:
        return False, str(exc)
    except Exception as exc:
        logger.error("add_attendee error: %s", exc)
        return False, str(exc)


def _publish_session_updated(session_id, title, start_dt, end_dt, location) -> tuple[bool, str]:
    """Publish a session_updated message. Returns (success, method)."""
    try:
        xml = build_session_updated_xml(
            session_id=session_id,
            title=title,
            start_datetime=start_dt,
            end_datetime=end_dt,
            location=location,
        )
        if _rabbit_publish("planning.exchange", "planning.session.updated", xml):
            return True, "rabbitmq"
    except Exception as exc:
        logger.warning("session_updated build/publish failed: %s", exc)

    ok = _db_update_session(session_id, title, start_dt, end_dt, location)
    return ok, "direct_db"


# ---------------------------------------------------------------------------
# HTML page
# ---------------------------------------------------------------------------

def _html(client_id: str) -> str:
    msal_configured = "true" if client_id else "false"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Planning Demo — Frontend</title>
  <script src="/static/msal-browser.min.js"></script>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh}}
    .topbar{{background:#1e293b;border-bottom:1px solid #334155;padding:14px 32px;
             display:flex;justify-content:space-between;align-items:center}}
    .topbar h1{{font-size:1.1rem;font-weight:700;color:#f8fafc}}
    .topbar small{{color:#64748b;margin-left:8px;font-weight:400}}
    .user-pill{{display:flex;align-items:center;gap:10px;background:#0f172a;
               border-radius:9999px;padding:6px 14px;font-size:0.875rem}}
    .avatar{{width:32px;height:32px;border-radius:50%;background:#3b82f6;
             display:flex;align-items:center;justify-content:center;font-weight:700;font-size:0.8rem}}
    .main{{max-width:1200px;margin:0 auto;padding:32px 24px;display:grid;
           grid-template-columns:1fr 380px;gap:24px}}
    @media(max-width:900px){{.main{{grid-template-columns:1fr}}}}
    .card{{background:#1e293b;border:1px solid #334155;border-radius:12px;padding:24px}}
    .card h2{{font-size:1rem;font-weight:700;color:#f1f5f9;margin-bottom:16px;
              display:flex;align-items:center;gap:8px}}
    label{{display:block;font-size:0.8rem;color:#94a3b8;margin-bottom:4px;margin-top:12px}}
    input,select{{width:100%;background:#0f172a;border:1px solid #334155;border-radius:8px;
                 padding:8px 12px;color:#f1f5f9;font-size:0.875rem}}
    input:focus,select:focus{{outline:none;border-color:#3b82f6}}
    .btn{{display:inline-flex;align-items:center;gap:6px;padding:9px 18px;
          border-radius:8px;border:none;cursor:pointer;font-size:0.875rem;
          font-weight:600;transition:opacity .15s}}
    .btn:hover{{opacity:.85}}
    .btn-primary{{background:#3b82f6;color:white}}
    .btn-ms{{background:#2563eb;color:white}}
    .btn-success{{background:#22c55e;color:white}}
    .btn-warning{{background:#f59e0b;color:white}}
    .btn-outline{{background:transparent;color:#94a3b8;border:1px solid #334155}}
    .btn-sm{{padding:5px 12px;font-size:0.8rem}}
    .session-card{{background:#0f172a;border:1px solid #334155;border-radius:10px;
                  padding:16px;margin-bottom:12px}}
    .session-card h3{{font-size:0.95rem;font-weight:600;color:#f1f5f9;margin-bottom:6px}}
    .session-meta{{font-size:0.8rem;color:#64748b;display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px}}
    .tag{{background:#1e293b;border:1px solid #334155;border-radius:9999px;
          padding:2px 8px;font-size:0.75rem}}
    .badge{{border-radius:9999px;padding:2px 8px;font-size:0.72rem;font-weight:600}}
    .b-synced{{background:#14532d;color:#86efac}}
    .b-not_synced{{background:#1e293b;color:#64748b}}
    .b-failed{{background:#7f1d1d;color:#fca5a5}}
    .b-pending{{background:#78350f;color:#fcd34d}}
    .toast{{position:fixed;bottom:24px;right:24px;background:#1e293b;border:1px solid #334155;
            border-radius:10px;padding:14px 20px;font-size:0.875rem;max-width:380px;
            box-shadow:0 8px 24px rgba(0,0,0,.4);display:none;z-index:999}}
    .toast.show{{display:block}}
    .toast.ok{{border-color:#22c55e;color:#86efac}}
    .toast.err{{border-color:#ef4444;color:#fca5a5}}
    .empty{{text-align:center;color:#475569;padding:32px;font-size:0.875rem}}
    .spinner{{display:inline-block;width:14px;height:14px;border:2px solid #334155;
              border-top-color:#3b82f6;border-radius:50%;animation:spin .6s linear infinite}}
    @keyframes spin{{to{{transform:rotate(360deg)}}}}
    .flow{{display:flex;align-items:center;gap:8px;flex-wrap:wrap;
           background:#0f172a;border-radius:8px;padding:12px;margin-bottom:16px;font-size:0.78rem}}
    .flow-step{{background:#1e293b;border:1px solid #334155;border-radius:6px;
               padding:4px 10px;color:#94a3b8}}
    .flow-arrow{{color:#334155;font-weight:bold}}
    .flow-step.active{{border-color:#3b82f6;color:#93c5fd}}
    #loginSection{{text-align:center;padding:16px 0}}
    #userSection{{display:none}}
    .edit-panel{{display:none;margin-top:12px;padding-top:12px;border-top:1px solid #334155}}
    .edit-panel input{{margin-bottom:6px;background:#1e293b}}
    .edit-row{{display:grid;grid-template-columns:1fr 1fr;gap:8px}}
    .btn-actions{{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}}
  </style>
</head>
<body>

<div class="topbar">
  <div>
    <h1>Planning Service <small>Frontend Demo</small></h1>
  </div>
  <div id="loginSection">
    <button class="btn btn-ms" onclick="msLogin()">
      <svg width="16" height="16" viewBox="0 0 21 21" fill="none">
        <rect x="1" y="1" width="9" height="9" fill="#f25022"/>
        <rect x="11" y="1" width="9" height="9" fill="#7fba00"/>
        <rect x="1" y="11" width="9" height="9" fill="#00a4ef"/>
        <rect x="11" y="11" width="9" height="9" fill="#ffb900"/>
      </svg>
      Sign in with Microsoft
    </button>
  </div>
  <div id="userSection" class="user-pill">
    <div class="avatar" id="userInitial">?</div>
    <div>
      <div style="font-weight:600;color:#f1f5f9" id="userName">—</div>
      <div style="font-size:0.75rem;color:#64748b" id="userEmail">—</div>
    </div>
    <button class="btn btn-outline btn-sm" onclick="msLogout()" style="margin-left:8px">Sign out</button>
  </div>
</div>

<div class="main">

  <!-- Left: sessions list -->
  <div>
    <div class="card" style="margin-bottom:24px">
      <h2>📋 Message Flow</h2>
      <div class="flow">
        <span class="flow-step active">Frontend</span>
        <span class="flow-arrow">→</span>
        <span class="flow-step">calendar.invite<br><small>RabbitMQ</small></span>
        <span class="flow-arrow">→</span>
        <span class="flow-step">consumer.py<br><small>Planning</small></span>
        <span class="flow-arrow">→</span>
        <span class="flow-step">graph_service<br><small>Outlook</small></span>
        <span class="flow-arrow">→</span>
        <span class="flow-step">session_created<br><small>planning.exchange</small></span>
      </div>
      <p style="font-size:0.8rem;color:#64748b">
        Joining a session adds the event to your personal Outlook calendar (requires sign-in).
        Editing publishes a <code style="color:#93c5fd">session_updated</code> message via RabbitMQ.
      </p>
    </div>

    <div class="card">
      <h2>
        📅 Available Sessions
        <button class="btn btn-outline btn-sm" onclick="loadSessions()" style="margin-left:auto">↻ Refresh</button>
      </h2>
      <div id="sessionsList"><div class="empty"><span class="spinner"></span> Loading…</div></div>
    </div>
  </div>

  <!-- Right: create / status -->
  <div>
    <div class="card">
      <h2>➕ Create Session</h2>

      <label>Title</label>
      <input id="title" type="text" placeholder="Keynote: AI in Healthcare" value="Keynote: AI in Healthcare"/>

      <label>Start</label>
      <input id="start" type="datetime-local" value="2026-05-15T14:00"/>

      <label>End</label>
      <input id="end" type="datetime-local" value="2026-05-15T15:00"/>

      <label>Location</label>
      <input id="location" type="text" placeholder="Aula A - Campus Jette" value="Aula A - Campus Jette"/>

      <label>Session Type</label>
      <select id="session_type">
        <option value="keynote">Keynote</option>
        <option value="workshop">Workshop</option>
        <option value="panel">Panel</option>
        <option value="networking">Networking</option>
      </select>

      <div style="margin-top:20px">
        <button class="btn btn-primary" style="width:100%" onclick="createSession()">
          📤 Publish calendar.invite
        </button>
      </div>

      <div id="lastXml" style="display:none;margin-top:16px">
        <div style="font-size:0.75rem;color:#64748b;margin-bottom:6px">Published XML</div>
        <pre id="xmlPreview" style="background:#0f172a;border:1px solid #334155;border-radius:8px;
             padding:12px;font-size:0.7rem;color:#86efac;overflow-x:auto;white-space:pre-wrap"></pre>
      </div>
    </div>

    <div class="card" style="margin-top:16px">
      <h2>ℹ️ Status</h2>
      <div id="statusPanel" style="font-size:0.8rem;color:#64748b">
        Waiting for action…
      </div>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
// ─── MSAL ─────────────────────────────────────────────────────────────────
const MSAL_CONFIGURED = {msal_configured};
const CLIENT_ID = "{client_id or 'REPLACE_WITH_CLIENT_ID'}";

const msalConfig = {{
  auth: {{
    clientId: CLIENT_ID,
    authority: "https://login.microsoftonline.com/common",
    redirectUri: window.location.origin,
  }},
  cache: {{ cacheLocation: "sessionStorage" }},
}};

const GRAPH_SCOPES = ["User.Read", "Calendars.ReadWrite"];

let msalInstance = null;
let currentUser = null;
let graphAccessToken = null;

async function initMsal() {{
  if (!MSAL_CONFIGURED) return;
  try {{
    msalInstance = new msal.PublicClientApplication(msalConfig);
    const resp = await msalInstance.handleRedirectPromise();
    if (resp) {{
      graphAccessToken = resp.accessToken;
      setUser(resp.account);
    }} else {{
      const accounts = msalInstance.getAllAccounts();
      if (accounts.length > 0) setUser(accounts[0]);
    }}
  }} catch(e) {{ console.warn("MSAL init:", e); }}
}}

async function msLogin() {{
  if (!MSAL_CONFIGURED) {{
    setUser({{ name: "Demo User", username: "demo@planning.local", localAccountId: "demo-001" }});
    return;
  }}
  // If not initialized yet, try once more
  if (!msalInstance) {{
    await initMsal();
  }}
  if (!msalInstance) {{
    showToast("MSAL failed to load — check that AZURE_CLIENT_ID is set and refresh the page.", "err");
    return;
  }}
  try {{
    const resp = await msalInstance.loginPopup({{ scopes: GRAPH_SCOPES }});
    graphAccessToken = resp.accessToken;
    setUser(resp.account);
  }} catch(e) {{ showToast("Login failed: " + e.message, "err"); }}
}}

async function getGraphToken() {{
  if (!msalInstance || !currentUser) return null;
  try {{
    const result = await msalInstance.acquireTokenSilent({{
      scopes: GRAPH_SCOPES,
      account: currentUser,
    }});
    return result.accessToken;
  }} catch(e) {{
    // Silent failed — try popup
    try {{
      const result = await msalInstance.acquireTokenPopup({{ scopes: GRAPH_SCOPES }});
      return result.accessToken;
    }} catch(e2) {{ return null; }}
  }}
}}

function msLogout() {{
  currentUser = null;
  graphAccessToken = null;
  document.getElementById("loginSection").style.display = "";
  document.getElementById("userSection").style.display = "none";
  if (msalInstance) msalInstance.logoutPopup().catch(()=>{{}});
}}

function setUser(account) {{
  currentUser = account;
  const name = account.name || account.username || "User";
  const email = account.username || "";
  document.getElementById("userName").textContent = name;
  document.getElementById("userEmail").textContent = email;
  document.getElementById("userInitial").textContent = name.charAt(0).toUpperCase();
  document.getElementById("loginSection").style.display = "none";
  document.getElementById("userSection").style.display = "flex";
  setStatus(`✅ Signed in as <b>${{name}}</b> — joining a session will add it to your Outlook calendar.`);
}}

// ─── Add user as attendee to the planning event ───────────────────────────
async function addToMyCalendar(sessionId, title, startIso, endIso, location) {{
  if (!currentUser) {{
    setStatus("⚠️ Not signed in — sign in to add to your calendar.");
    return false;
  }}
  const email = currentUser.username;
  try {{
    const r = await fetch(`/api/sessions/${{sessionId}}/attend`, {{
      method: "POST",
      headers: {{"Content-Type": "application/json"}},
      body: JSON.stringify({{ attendee_email: email }}),
    }});
    const data = await r.json();
    if (data.ok) {{
      setStatus(`✅ <b>${{email}}</b> ajouté comme attendee — tu recevras l'invite Outlook.`);
      return true;
    }} else {{
      setStatus(`⚠️ ${{data.error || "Could not add attendee"}}`);
      return false;
    }}
  }} catch(e) {{
    setStatus("⚠️ " + e.message);
    return false;
  }}
}}

// ─── Sessions ─────────────────────────────────────────────────────────────
async function loadSessions() {{
  document.getElementById("sessionsList").innerHTML =
    '<div class="empty"><span class="spinner"></span> Loading…</div>';
  try {{
    const r = await fetch("/api/sessions");
    const sessions = await r.json();
    renderSessions(sessions);
  }} catch(e) {{
    document.getElementById("sessionsList").innerHTML =
      '<div class="empty">⚠️ Could not reach backend — is the demo server running?</div>';
  }}
}}

function toLocalInput(isoStr) {{
  if (!isoStr) return "";
  // "2026-05-15T14:00:00+00:00" → "2026-05-15T14:00"
  return isoStr.replace("Z","").replace("+00:00","").slice(0,16);
}}

function renderSessions(sessions) {{
  const el = document.getElementById("sessionsList");
  if (!sessions.length) {{
    el.innerHTML = '<div class="empty">No sessions yet. Create one →</div>';
    return;
  }}
  el.innerHTML = sessions.map(s => {{
    const start = s.start_datetime ? new Date(s.start_datetime).toLocaleString() : "—";
    const outlook = s.outlook_status || "not_synced";
    const outlookLabel = {{synced:"✅ In Outlook",failed:"❌ Sync failed",
                          pending:"⏳ Pending",deleted:"🗑 Cancelled",not_synced:"—"}};
    const sid = s.session_id;
    const safeTitle = (s.title||"").replace(/'/g,"\\'").replace(/"/g,"&quot;");
    const startIso = s.start_datetime || "";
    const endIso   = s.end_datetime   || "";
    const safeLoc  = (s.location||"").replace(/'/g,"\\'").replace(/"/g,"&quot;");

    return `
    <div class="session-card" id="card-${{sid}}">
      <h3>${{s.title || "Untitled"}}</h3>
      <div class="session-meta">
        <span>🕐 ${{start}}</span>
        <span>📍 ${{s.location || "—"}}</span>
        <span class="tag">${{s.session_type || "keynote"}}</span>
        <span class="badge b-${{outlook}}">${{outlookLabel[outlook] || outlook}}</span>
      </div>
      <div class="btn-actions">
        <button class="btn btn-success btn-sm"
          onclick="joinSession('${{sid}}','${{safeTitle}}','${{startIso}}','${{endIso}}','${{safeLoc}}')">
          📩 Join &amp; Add to Calendar
        </button>
        <button class="btn btn-warning btn-sm" onclick="toggleEdit('${{sid}}')">
          ✏️ Edit
        </button>
      </div>

      <!-- Inline edit form -->
      <div class="edit-panel" id="edit-${{sid}}">
        <label>Title</label>
        <input id="e-title-${{sid}}" value="${{safeTitle}}"/>
        <div class="edit-row">
          <div>
            <label>Start</label>
            <input id="e-start-${{sid}}" type="datetime-local" value="${{toLocalInput(startIso)}}"/>
          </div>
          <div>
            <label>End</label>
            <input id="e-end-${{sid}}" type="datetime-local" value="${{toLocalInput(endIso)}}"/>
          </div>
        </div>
        <label>Location</label>
        <input id="e-loc-${{sid}}" value="${{safeLoc}}"/>
        <div class="btn-actions" style="margin-top:12px">
          <button class="btn btn-primary btn-sm" onclick="submitEdit('${{sid}}')">💾 Save &amp; Publish</button>
          <button class="btn btn-outline btn-sm" onclick="toggleEdit('${{sid}}')">Cancel</button>
        </div>
      </div>
    </div>`;
  }}).join("");
}}

// ─── Create session ────────────────────────────────────────────────────────
async function createSession() {{
  const title    = document.getElementById("title").value.trim();
  const start    = document.getElementById("start").value;
  const end      = document.getElementById("end").value;
  const location = document.getElementById("location").value.trim();

  if (!title || !start || !end) {{
    showToast("Fill in Title, Start, and End first.", "err"); return;
  }}

  setStatus("⏳ Publishing <code>calendar.invite</code> to RabbitMQ…");

  try {{
    const r = await fetch("/api/sessions", {{
      method: "POST",
      headers: {{"Content-Type": "application/json"}},
      body: JSON.stringify({{
        title,
        start_datetime: start + ":00Z",
        end_datetime:   end   + ":00Z",
        location,
        requested_by: currentUser ? currentUser.username : "demo-user",
      }})
    }});
    const data = await r.json();
    if (data.ok) {{
      showToast(`✅ Session created via ${{data.method}}`, "ok");
      setStatus(`✅ <b>calendar.invite</b> published via <b>${{data.method}}</b><br>
        <span style="color:#64748b">Session ID: ${{data.session_id}}</span>`);
      document.getElementById("xmlPreview").textContent = data.xml || "";
      document.getElementById("lastXml").style.display = "block";
      loadSessions();
    }} else {{
      showToast("❌ " + (data.error || "Unknown error"), "err");
      setStatus("❌ " + (data.error || "Unknown error"));
    }}
  }} catch(e) {{
    showToast("❌ Network error: " + e.message, "err");
  }}
}}

// ─── Join session ──────────────────────────────────────────────────────────
async function joinSession(id, title, startIso, endIso, location) {{
  setStatus(`⏳ Joining <b>${{title}}</b>…`);

  // 1. Notify the backend (RabbitMQ / DB)
  try {{
    const r = await fetch(`/api/sessions/${{id}}/join`, {{
      method: "POST",
      headers: {{"Content-Type": "application/json"}},
      body: JSON.stringify({{
        requested_by: currentUser ? currentUser.username : "demo-user",
        title, start_datetime: startIso, end_datetime: endIso, location,
      }})
    }});
    const data = await r.json();
    if (!data.ok) {{
      showToast("❌ " + (data.error || "Failed"), "err"); return;
    }}
  }} catch(e) {{
    showToast("❌ " + e.message, "err"); return;
  }}

  // 2. If signed in, add user as attendee to the planning event
  if (currentUser) {{
    const calOk = await addToMyCalendar(id, title, startIso, endIso, location);
    if (calOk) {{
      showToast(`✅ Joined & added to your Outlook calendar`, "ok");
    }} else {{
      showToast(`✅ Joined (calendar sync pending)`, "ok");
    }}
  }} else {{
    showToast(`✅ Joined: ${{title}} (sign in to add to your calendar)`, "ok");
    setStatus(`✅ Joined <b>${{title}}</b> — <a href="#" onclick="msLogin()" style="color:#93c5fd">Sign in</a> to add to your Outlook calendar.`);
  }}
}}

// ─── Edit session ──────────────────────────────────────────────────────────
function toggleEdit(sid) {{
  const panel = document.getElementById("edit-" + sid);
  panel.style.display = panel.style.display === "block" ? "none" : "block";
}}

async function submitEdit(sid) {{
  const title    = document.getElementById("e-title-" + sid).value.trim();
  const start    = document.getElementById("e-start-" + sid).value;
  const end      = document.getElementById("e-end-"   + sid).value;
  const location = document.getElementById("e-loc-"   + sid).value.trim();

  if (!title || !start || !end) {{
    showToast("Title, Start and End are required.", "err"); return;
  }}

  setStatus(`⏳ Publishing <code>session_updated</code> for <b>${{title}}</b>…`);

  try {{
    const r = await fetch(`/api/sessions/${{sid}}`, {{
      method: "PATCH",
      headers: {{"Content-Type": "application/json"}},
      body: JSON.stringify({{
        title,
        start_datetime: start + ":00Z",
        end_datetime:   end   + ":00Z",
        location,
      }})
    }});
    const data = await r.json();
    if (data.ok) {{
      showToast(`✅ Session updated via ${{data.method}}`, "ok");
      setStatus(`✅ <b>session_updated</b> published via <b>${{data.method}}</b>`);
      toggleEdit(sid);
      loadSessions();
    }} else {{
      showToast("❌ " + (data.error || "Update failed"), "err");
      setStatus("❌ " + (data.error || "Update failed"));
    }}
  }} catch(e) {{
    showToast("❌ " + e.message, "err");
  }}
}}

// ─── Helpers ───────────────────────────────────────────────────────────────
function showToast(msg, type="ok") {{
  const t = document.getElementById("toast");
  t.innerHTML = msg;
  t.className = "toast show " + type;
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.className = "toast", 3500);
}}

function setStatus(html) {{
  document.getElementById("statusPanel").innerHTML = html;
}}

// ─── Init ──────────────────────────────────────────────────────────────────
initMsal();
loadSessions();
setInterval(loadSessions, 15000);
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class DemoHandler(BaseHTTPRequestHandler):

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    def do_GET(self):
        try:
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                html = _html(CLIENT_ID).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html)))
                self.end_headers()
                self.wfile.write(html)
            elif path == "/api/sessions":
                self._send_json(_db_sessions())
            elif path.startswith("/static/"):
                filename = path[len("/static/"):]
                filepath = _STATIC_DIR / filename
                if filepath.exists():
                    data = filepath.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/javascript")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                else:
                    self._send_json({"error": "not found"}, 404)
            else:
                self._send_json({"error": "not found"}, 404)
        except (ConnectionAbortedError, BrokenPipeError):
            pass

    def do_POST(self):
        try:
            path = urlparse(self.path).path
            body = self._read_body()

            if path == "/api/sessions":
                session_id = str(uuid.uuid4())
                title    = body.get("title", "New Session")
                start_dt = body.get("start_datetime", "")
                end_dt   = body.get("end_datetime", "")
                location = body.get("location", "")

                ok, method = _publish_calendar_invite(session_id, title, start_dt, end_dt, location)

                try:
                    xml_preview = build_calendar_invite_xml(
                        session_id=session_id, title=title,
                        start_datetime=start_dt, end_datetime=end_dt, location=location,
                    )
                except Exception:
                    xml_preview = ""

                self._send_json({"ok": ok, "session_id": session_id, "method": method, "xml": xml_preview})

            elif path.endswith("/join"):
                parts = path.strip("/").split("/")
                session_id = parts[2] if len(parts) >= 4 else body.get("session_id", "")
                ok, method = _publish_calendar_invite(
                    session_id,
                    body.get("title", ""),
                    body.get("start_datetime", ""),
                    body.get("end_datetime", ""),
                    body.get("location", ""),
                )
                self._send_json({"ok": ok, "method": method})

            elif path.endswith("/attend"):
                # POST /api/sessions/{id}/attend
                parts = path.strip("/").split("/")
                session_id = parts[2] if len(parts) >= 4 else ""
                attendee_email = body.get("attendee_email", "")
                if not session_id or not attendee_email:
                    self._send_json({"ok": False, "error": "Missing session_id or attendee_email"}, 400)
                    return
                ok, error = _add_attendee_to_event(session_id, attendee_email)
                self._send_json({"ok": ok, "error": error})

            else:
                self._send_json({"error": "not found"}, 404)

        except (ConnectionAbortedError, BrokenPipeError):
            pass
        except Exception as exc:
            logger.error("POST handler error: %s", exc, exc_info=True)
            try:
                self._send_json({"ok": False, "error": str(exc)}, 500)
            except Exception:
                pass

    def do_PATCH(self):
        try:
            path = urlparse(self.path).path
            body = self._read_body()

            # PATCH /api/sessions/{id}
            parts = path.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "api" and parts[1] == "sessions":
                session_id = parts[2]
                title    = body.get("title", "")
                start_dt = body.get("start_datetime", "")
                end_dt   = body.get("end_datetime", "")
                location = body.get("location", "")

                if not all([session_id, title, start_dt, end_dt]):
                    self._send_json({"ok": False, "error": "Missing required fields"}, 400)
                    return

                ok, method = _publish_session_updated(session_id, title, start_dt, end_dt, location)
                self._send_json({"ok": ok, "session_id": session_id, "method": method})
            else:
                self._send_json({"error": "not found"}, 404)

        except (ConnectionAbortedError, BrokenPipeError):
            pass
        except Exception as exc:
            logger.error("PATCH handler error: %s", exc, exc_info=True)
            try:
                self._send_json({"ok": False, "error": str(exc)}, 500)
            except Exception:
                pass

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    _ensure_msal()
    ms_status = (
        f"Microsoft login enabled (client ID: {CLIENT_ID})"
        if CLIENT_ID
        else "Demo login mode (set AZURE_CLIENT_ID for real Microsoft login)"
    )
    logger.info("Frontend demo running at http://localhost:%d", DEMO_PORT)
    logger.info(ms_status)
    logger.info("NOTE: Add http://localhost:%d as a redirect URI (SPA) in your Azure app", DEMO_PORT)
    server = HTTPServer(("0.0.0.0", DEMO_PORT), DemoHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
