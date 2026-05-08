"""
Planning Service — Sync Status Dashboard
Serves a simple HTML page showing graph_sync and message_log status.
Run: python dashboard.py
Then open: http://localhost:8088
"""

import os
import json
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timezone
from dotenv import load_dotenv
from db_config import get_database_url

load_dotenv()

logger = logging.getLogger(__name__)

DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8088"))

_DB_URL = get_database_url(default_host="localhost", default_port="5433")


def _query(sql: str, params=None) -> list[dict]:
    try:
        import psycopg2
        from psycopg2.extras import DictCursor
        with psycopg2.connect(_DB_URL, cursor_factory=DictCursor, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return [dict(row) for row in cur.fetchall()]
    except Exception as exc:
        logger.error("Dashboard DB query failed: %s", exc)
        return []


def _fetch_data() -> dict:
    session_rows = _query(
        """
        SELECT s.session_id, s.title, s.start_datetime, s.end_datetime,
               s.location, s.session_type, s.status, s.current_attendees,
               s.created_at, s.updated_at, s.is_deleted,
               COALESCE(gs.sync_status, 'not_synced') AS outlook_status,
               gs.graph_event_id
        FROM sessions s
        LEFT JOIN graph_sync gs ON gs.session_id = s.session_id
        ORDER BY s.start_datetime ASC
        LIMIT 100
        """
    )
    graph_rows = _query(
        """
        SELECT gs.session_id, gs.graph_event_id, gs.sync_status,
               gs.last_synced_at, gs.error_message,
               s.title, s.start_datetime, s.end_datetime, s.location
        FROM graph_sync gs
        LEFT JOIN sessions s ON s.session_id = gs.session_id
        ORDER BY gs.last_synced_at DESC NULLS LAST
        LIMIT 50
        """
    )
    message_rows = _query(
        """
        SELECT message_id, message_type, source, status, error_message, processed_at
        FROM message_log
        ORDER BY processed_at DESC
        LIMIT 30
        """
    )
    counts = _query(
        """
        SELECT
            (SELECT COUNT(*) FROM sessions WHERE is_deleted = FALSE)        AS active_sessions,
            (SELECT COUNT(*) FROM graph_sync WHERE sync_status = 'synced')  AS synced,
            (SELECT COUNT(*) FROM graph_sync WHERE sync_status = 'failed')  AS failed,
            (SELECT COUNT(*) FROM graph_sync WHERE sync_status = 'deleted') AS deleted,
            (SELECT COUNT(*) FROM message_log WHERE status = 'failed')      AS failed_messages
        """
    )
    return {
        "sessions": session_rows,
        "graph_sync": graph_rows,
        "message_log": message_rows,
        "counts": counts[0] if counts else {},
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }


def _status_badge(status: str) -> str:
    colors = {
        "synced":    ("#22c55e", "white"),
        "failed":    ("#ef4444", "white"),
        "deleted":   ("#6b7280", "white"),
        "pending":   ("#f59e0b", "white"),
        "processed": ("#22c55e", "white"),
        "received":  ("#3b82f6", "white"),
        "ok":        ("#22c55e", "white"),
        "not_found": ("#f59e0b", "white"),
    }
    bg, fg = colors.get(str(status).lower(), ("#e5e7eb", "#374151"))
    return (
        f'<span style="background:{bg};color:{fg};padding:2px 8px;'
        f'border-radius:9999px;font-size:0.75rem;font-weight:600">{status}</span>'
    )


def _fmt(value) -> str:
    if value is None:
        return '<span style="color:#9ca3af">—</span>'
    s = str(value)
    if len(s) > 60:
        return f'<span title="{s}">{s[:57]}…</span>'
    return s


def _build_html(data: dict) -> str:
    c = data["counts"]

    def stat_card(label, value, color):
        return f"""
        <div style="background:white;border-radius:12px;padding:24px;
                    box-shadow:0 1px 3px rgba(0,0,0,.1);text-align:center;min-width:140px">
          <div style="font-size:2rem;font-weight:700;color:{color}">{value}</div>
          <div style="color:#6b7280;font-size:0.875rem;margin-top:4px">{label}</div>
        </div>"""

    stats = "".join([
        stat_card("Active Sessions",   c.get("active_sessions", "?"), "#3b82f6"),
        stat_card("Synced to Outlook", c.get("synced",          "?"), "#22c55e"),
        stat_card("Sync Failed",       c.get("failed",          "?"), "#ef4444"),
        stat_card("Cancelled",         c.get("deleted",         "?"), "#6b7280"),
        stat_card("Failed Messages",   c.get("failed_messages", "?"), "#f59e0b"),
    ])

    # Sessions table
    session_rows_html = ""
    for r in data["sessions"]:
        deleted = r.get("is_deleted")
        row_style = ' style="opacity:0.5"' if deleted else ""
        session_rows_html += f"""
        <tr{row_style}>
          <td style="font-family:monospace;font-size:0.75rem">{_fmt(r.get("session_id"))}</td>
          <td><b>{_fmt(r.get("title"))}</b></td>
          <td>{_fmt(r.get("start_datetime"))}</td>
          <td>{_fmt(r.get("end_datetime"))}</td>
          <td>{_fmt(r.get("location"))}</td>
          <td>{_fmt(r.get("session_type"))}</td>
          <td>{_status_badge(r.get("status", ""))}</td>
          <td>{_status_badge(r.get("outlook_status", "not_synced"))}</td>
          <td>{_fmt(r.get("current_attendees"))}</td>
          <td>{_fmt(r.get("created_at"))}</td>
          <td>{_fmt(r.get("updated_at"))}</td>
        </tr>"""

    if not session_rows_html:
        session_rows_html = (
            '<tr><td colspan="11" style="text-align:center;color:#9ca3af;padding:24px">'
            "No sessions yet</td></tr>"
        )

    # Graph sync table
    graph_rows_html = ""
    for r in data["graph_sync"]:
        graph_rows_html += f"""
        <tr>
          <td>{_fmt(r.get("session_id"))}</td>
          <td>{_fmt(r.get("title"))}</td>
          <td>{_fmt(r.get("start_datetime"))}</td>
          <td>{_fmt(r.get("location"))}</td>
          <td>{_status_badge(r.get("sync_status", ""))}</td>
          <td>{_fmt(r.get("graph_event_id"))}</td>
          <td>{_fmt(r.get("last_synced_at"))}</td>
          <td style="color:#ef4444;font-size:0.75rem">{_fmt(r.get("error_message"))}</td>
        </tr>"""

    if not graph_rows_html:
        graph_rows_html = (
            '<tr><td colspan="8" style="text-align:center;color:#9ca3af;padding:24px">'
            "No sync records yet</td></tr>"
        )

    # Message log table
    msg_rows_html = ""
    for r in data["message_log"]:
        msg_rows_html += f"""
        <tr>
          <td style="font-family:monospace;font-size:0.75rem">{_fmt(r.get("message_id"))}</td>
          <td>{_fmt(r.get("message_type"))}</td>
          <td>{_fmt(r.get("source"))}</td>
          <td>{_status_badge(r.get("status", ""))}</td>
          <td>{_fmt(r.get("processed_at"))}</td>
          <td style="color:#ef4444;font-size:0.75rem">{_fmt(r.get("error_message"))}</td>
        </tr>"""

    if not msg_rows_html:
        msg_rows_html = (
            '<tr><td colspan="6" style="text-align:center;color:#9ca3af;padding:24px">'
            "No messages yet</td></tr>"
        )

    table_style = """
        width:100%;border-collapse:collapse;font-size:0.875rem;
    """
    th_style = """
        background:#f9fafb;padding:10px 14px;text-align:left;font-weight:600;
        color:#374151;border-bottom:2px solid #e5e7eb;white-space:nowrap;
    """
    td_style = "padding:10px 14px;border-bottom:1px solid #f3f4f6;vertical-align:top;"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <meta http-equiv="refresh" content="30"/>
  <title>Planning Service — Sync Dashboard</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: system-ui, sans-serif; background: #f3f4f6; color: #111827; }}
    h2 {{ font-size: 1.125rem; font-weight: 700; margin-bottom: 12px; color: #1f2937; }}
    table {{ {table_style} }}
    th {{ {th_style} }}
    td {{ {td_style} }}
    tr:hover td {{ background: #f9fafb; }}
    .card {{ background: white; border-radius: 12px; padding: 24px;
             box-shadow: 0 1px 3px rgba(0,0,0,.1); margin-bottom: 24px; overflow-x: auto; }}
    .badge-flow {{
      display: inline-flex; align-items: center; gap: 8px;
      background: #eff6ff; border: 1px solid #bfdbfe;
      border-radius: 8px; padding: 8px 16px; font-size: 0.8rem; color: #1d4ed8;
    }}
    .arrow {{ color: #93c5fd; font-weight: bold; }}
  </style>
</head>
<body>
<div style="max-width:1400px;margin:0 auto;padding:24px">

  <!-- Header -->
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:24px">
    <div>
      <h1 style="font-size:1.5rem;font-weight:700">Planning Service — Sync Dashboard</h1>
      <p style="color:#6b7280;font-size:0.875rem;margin-top:4px">
        Auto-refresh every 30 seconds · Generated at {data["generated_at"]}
      </p>
    </div>
    <button onclick="location.reload()"
            style="background:#3b82f6;color:white;border:none;border-radius:8px;
                   padding:8px 16px;cursor:pointer;font-size:0.875rem">
      ↻ Refresh
    </button>
  </div>

  <!-- Flow diagram -->
  <div class="card" style="margin-bottom:24px">
    <h2>Message Flow</h2>
    <div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:12px">
      <span class="badge-flow">RabbitMQ<br><small>calendar.invite / session.*</small></span>
      <span class="arrow">→</span>
      <span class="badge-flow">consumer.py<br><small>parse + DB persist</small></span>
      <span class="arrow">→</span>
      <span class="badge-flow">graph_service.py<br><small>sync_created/updated/deleted</small></span>
      <span class="arrow">→</span>
      <span class="badge-flow">Microsoft Graph API<br><small>Outlook calendar</small></span>
    </div>
    <div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:12px">
      <span class="badge-flow">Session data<br><small>title / datetime / location</small></span>
      <span class="arrow">→</span>
      <span class="badge-flow">producer.py<br><small>XSD validate + retry</small></span>
      <span class="arrow">→</span>
      <span class="badge-flow">planning.exchange<br><small>session_created/updated/deleted</small></span>
    </div>
  </div>

  <!-- Stat cards -->
  <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:24px">
    {stats}
  </div>

  <!-- Sessions table -->
  <div class="card" style="margin-bottom:24px">
    <h2>All Sessions (sessions)</h2>
    <table>
      <thead>
        <tr>
          <th>Session ID</th>
          <th>Title</th>
          <th>Start</th>
          <th>End</th>
          <th>Location</th>
          <th>Type</th>
          <th>Status</th>
          <th>Outlook</th>
          <th>Attendees</th>
          <th>Created</th>
          <th>Updated</th>
        </tr>
      </thead>
      <tbody>{session_rows_html}</tbody>
    </table>
  </div>

  <!-- Graph sync table -->
  <div class="card">
    <h2>Outlook Calendar Sync (graph_sync)</h2>
    <table>
      <thead>
        <tr>
          <th>Session ID</th>
          <th>Title</th>
          <th>Start</th>
          <th>Location</th>
          <th>Sync Status</th>
          <th>Outlook Event ID</th>
          <th>Last Synced</th>
          <th>Error</th>
        </tr>
      </thead>
      <tbody>{graph_rows_html}</tbody>
    </table>
  </div>

  <!-- Message log table -->
  <div class="card">
    <h2>Message Log (last 30)</h2>
    <table>
      <thead>
        <tr>
          <th>Message ID</th>
          <th>Type</th>
          <th>Source</th>
          <th>Status</th>
          <th>Processed At</th>
          <th>Error</th>
        </tr>
      </thead>
      <tbody>{msg_rows_html}</tbody>
    </table>
  </div>

</div>
</body>
</html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ("/", "/index.html"):
            self.send_response(404)
            self.end_headers()
            return
        try:
            data = _fetch_data()
            html = _build_html(data).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
        except (ConnectionAbortedError, BrokenPipeError):
            pass  # Browser closed the connection — not an error

    def log_message(self, format, *args):
        pass  # silence access logs


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    server = HTTPServer(("0.0.0.0", DASHBOARD_PORT), DashboardHandler)
    logger.info("Dashboard running at http://localhost:%d", DASHBOARD_PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
