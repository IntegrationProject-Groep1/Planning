"""
Pytest configuration and shared fixtures for Planning service tests.
"""

import pytest
from datetime import datetime, timezone
import json


# ============================================================================
# SAMPLE DATA FIXTURES
# ============================================================================

@pytest.fixture
def sample_calendar_invite_xml():
    """Sample calendar.invite XML message."""
    return b"""<message xmlns="urn:integration:planning:v1">
        <header>
            <message_id>msg-001</message_id>
            <timestamp>2026-05-15T09:00:00Z</timestamp>
            <source>calendar</source>
            <type>calendar.invite</type>
        </header>
        <body>
            <session_id>sess-001</session_id>
            <title>Test Session</title>
            <start_datetime>2026-05-15T14:00:00Z</start_datetime>
            <end_datetime>2026-05-15T15:00:00Z</end_datetime>
            <location>online</location>
        </body>
    </message>"""


@pytest.fixture
def sample_session_created_xml():
    """Sample session_created XML message."""
    return b"""<message xmlns="urn:integration:planning:v1">
        <header>
            <message_id>msg-002</message_id>
            <timestamp>2026-05-15T09:00:00Z</timestamp>
            <source>planning</source>
            <type>session_created</type>
            <version>1.0</version>
            <correlation_id>corr-001</correlation_id>
        </header>
        <body>
            <session_id>sess-001</session_id>
            <title>Keynote: AI in Healthcare</title>
            <start_datetime>2026-05-15T14:00:00Z</start_datetime>
            <end_datetime>2026-05-15T15:00:00Z</end_datetime>
            <location>Aula A - Campus Jette</location>
            <session_type>keynote</session_type>
            <status>published</status>
            <max_attendees>120</max_attendees>
            <current_attendees>0</current_attendees>
        </body>
    </message>"""


@pytest.fixture
def sample_session_updated_xml():
    """Sample session_updated XML message."""
    return b"""<message xmlns="urn:integration:planning:v1">
        <header>
            <message_id>msg-003</message_id>
            <timestamp>2026-05-15T09:30:00Z</timestamp>
            <source>planning</source>
            <type>session_updated</type>
            <version>1.0</version>
            <correlation_id>corr-001</correlation_id>
        </header>
        <body>
            <session_id>sess-001</session_id>
            <title>Keynote: AI in Healthcare (Updated)</title>
            <start_datetime>2026-05-15T14:30:00Z</start_datetime>
            <end_datetime>2026-05-15T15:30:00Z</end_datetime>
            <location>Aula A - Campus Jette</location>
            <session_type>keynote</session_type>
            <status>published</status>
            <max_attendees>150</max_attendees>
            <current_attendees>25</current_attendees>
        </body>
    </message>"""


@pytest.fixture
def sample_session_deleted_xml():
    """Sample session_deleted XML message."""
    return b"""<message xmlns="urn:integration:planning:v1">
        <header>
            <message_id>msg-004</message_id>
            <timestamp>2026-05-15T10:00:00Z</timestamp>
            <source>planning</source>
            <type>session_deleted</type>
            <version>1.0</version>
            <correlation_id>corr-001</correlation_id>
        </header>
        <body>
            <session_id>sess-001</session_id>
            <reason>cancelled</reason>
            <deleted_by>planning-admin</deleted_by>
        </body>
    </message>"""


@pytest.fixture
def sample_session_view_request_xml():
    """Sample session_view_request XML message."""
    return b"""<message xmlns="urn:integration:planning:v1">
        <header>
            <message_id>req-001</message_id>
            <timestamp>2026-05-15T10:05:00Z</timestamp>
            <source>calendar</source>
            <type>session_view_request</type>
            <version>1.0</version>
            <correlation_id>corr-002</correlation_id>
        </header>
        <body>
            <session_id>sess-001</session_id>
        </body>
    </message>"""


@pytest.fixture
def sample_session_data():
    """Sample session data for database operations."""
    return {
        "session_id": "sess-test-001",
        "title": "Test Session",
        "start_datetime": "2026-05-15T14:00:00+00:00",
        "end_datetime": "2026-05-15T15:00:00+00:00",
        "location": "Conference Room A",
        "session_type": "keynote",
        "status": "published",
        "max_attendees": 100,
        "current_attendees": 10,
    }


@pytest.fixture
def sample_calendar_invite_data():
    """Sample calendar invite data for database operations."""
    return {
        "message_id": "msg-calendar-001",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "calendar",
        "type_": "calendar.invite",
        "session_id": "sess-test-001",
        "title": "Calendar Invite",
        "start_datetime": "2026-05-15T14:00:00+00:00",
        "end_datetime": "2026-05-15T15:00:00+00:00",
        "location": "online",
    }


# ============================================================================
# MOCK FIXTURES
# ============================================================================

@pytest.fixture
def mock_db_connection(mocker):
    """Mock database connection."""
    mock_conn = mocker.MagicMock()
    mock_cursor = mocker.MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    return mock_conn


# ============================================================================
# INVALID DATA FIXTURES
# ============================================================================

@pytest.fixture
def malformed_xml():
    """Malformed XML for testing error handling."""
    return b"<message><unclosed>"


@pytest.fixture
def xml_missing_header():
    """XML without header element."""
    return b"""<message xmlns="urn:integration:planning:v1">
        <body>
            <session_id>sess-001</session_id>
            <title>Test</title>
            <start_datetime>2026-05-15T14:00:00Z</start_datetime>
            <end_datetime>2026-05-15T15:00:00Z</end_datetime>
        </body>
    </message>"""


@pytest.fixture
def xml_missing_body():
    """XML without body element."""
    return b"""<message xmlns="urn:integration:planning:v1">
        <header>
            <message_id>msg-001</message_id>
            <timestamp>2026-05-15T09:00:00Z</timestamp>
            <source>calendar</source>
            <type>calendar.invite</type>
        </header>
    </message>"""


@pytest.fixture
def xml_missing_required_fields():
    """XML missing required fields."""
    return b"""<message xmlns="urn:integration:planning:v1">
        <header>
            <message_id>msg-001</message_id>
            <timestamp>2026-05-15T09:00:00Z</timestamp>
        </header>
        <body>
            <session_id>sess-001</session_id>
            <title>Test</title>
        </body>
    </message>"""
