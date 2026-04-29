"""
ICS/iCalendar feed generator.

Produces RFC 5545 iCalendar content from session data stored in the local DB.
Used to give non-Outlook users a subscribe-once feed they can import into any
calendar application (Apple Calendar, Google Calendar, Thunderbird, etc.).

The returned bytes can be served directly over HTTP with Content-Type text/calendar.
Replacing the http:// scheme with webcal:// in the URL makes calendar apps treat
the link as a direct subscription rather than a one-time download.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Union

from icalendar import Calendar, Event

logger = logging.getLogger(__name__)

_PRODID = "-//Planning Service//Desideriushogeschool Calendar//EN"


def build_ics(sessions: List[Dict], calendar_name: str = "Planning Sessions") -> bytes:
    """
    Build an RFC 5545 iCalendar byte string from a list of session dicts.

    Required keys per session: session_id, title, start_datetime, end_datetime
    Optional key: location

    start_datetime / end_datetime may be Python datetime objects or ISO 8601
    strings (e.g. "2026-05-15T14:00:00Z" or "2026-05-15 14:00:00+00:00").
    """
    cal = Calendar()
    cal.add("prodid", _PRODID)
    cal.add("version", "2.0")
    cal.add("x-wr-calname", calendar_name)
    cal.add("x-wr-timezone", "UTC")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")

    now = datetime.now(tz=timezone.utc)

    for session in sessions:
        event = Event()
        event.add("uid", f"{session['session_id']}@planning")
        event.add("summary", session["title"])
        event.add("dtstart", _to_dt(session["start_datetime"]))
        event.add("dtend", _to_dt(session["end_datetime"]))
        event.add("dtstamp", now)
        if session.get("location"):
            event.add("location", session["location"])
        cal.add_component(event)

    return cal.to_ical()


def _to_dt(value: Union[datetime, str]) -> datetime:
    """Normalise a session datetime value to a UTC-aware datetime."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    # String — try common formats
    for fmt in (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S+00:00",
        "%Y-%m-%d %H:%M:%S+00",
    ):
        try:
            dt = datetime.strptime(value, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    # Fallback: fromisoformat (Python 3.7+)
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
