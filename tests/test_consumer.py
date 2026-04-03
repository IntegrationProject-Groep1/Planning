import pytest
from unittest.mock import MagicMock, patch
from lxml import etree

from consumer import (
    validate_xml,
    handle_calendar_invite,
    on_message,
    get_session,
    reset_sessions_store,
)


def _strip_ns(root: etree._Element) -> etree._Element:
    for elem in root.iter():
        elem.tag = etree.QName(elem.tag).localname
    return root


def _make_valid_body(
    message_id="msg-001",
    source="calendar",
    session_id="sess-001",
    title="Test sessie",
    start_datetime="2026-05-15T14:00:00Z",
    end_datetime="2026-05-15T15:00:00Z",
    location="online",
) -> bytes:
    xml = f"""<message xmlns="urn:integration:planning:v1">
        <header>
            <message_id>{message_id}</message_id>
            <timestamp>2026-05-15T09:00:00Z</timestamp>
            <source>{source}</source>
            <type>calendar.invite</type>
        </header>
        <body>
            <session_id>{session_id}</session_id>
            <title>{title}</title>
            <start_datetime>{start_datetime}</start_datetime>
            <end_datetime>{end_datetime}</end_datetime>
            <location>{location}</location>
        </body>
    </message>"""
    return xml.encode("utf-8")


def _make_updated_body() -> bytes:
    xml = """<message xmlns="urn:integration:planning:v1">
        <header>
            <message_id>msg-upd-001</message_id>
            <timestamp>2026-05-15T09:00:00Z</timestamp>
            <source>frontend</source>
            <type>session_updated</type>
        </header>
        <body>
            <session_id>sess-001</session_id>
            <title>Updated session</title>
            <start_datetime>2026-05-15T16:00:00Z</start_datetime>
            <end_datetime>2026-05-15T17:00:00Z</end_datetime>
            <location>online</location>
        </body>
    </message>"""
    return xml.encode("utf-8")


def _make_created_body() -> bytes:
    xml = """<message xmlns="urn:integration:planning:v1">
        <header>
            <message_id>msg-cre-001</message_id>
            <timestamp>2026-05-15T09:00:00Z</timestamp>
            <source>planning</source>
            <type>session_created</type>
        </header>
        <body>
            <session_id>sess-001</session_id>
            <title>Created session</title>
            <start_datetime>2026-05-15T14:00:00Z</start_datetime>
            <end_datetime>2026-05-15T15:00:00Z</end_datetime>
            <location>online</location>
            <session_type>keynote</session_type>
            <status>published</status>
            <max_attendees>120</max_attendees>
            <current_attendees>0</current_attendees>
        </body>
    </message>"""
    return xml.encode("utf-8")


def _make_deleted_body() -> bytes:
    xml = """<message xmlns="urn:integration:planning:v1">
        <header>
            <message_id>msg-del-001</message_id>
            <timestamp>2026-05-15T09:00:00Z</timestamp>
            <source>frontend</source>
            <type>session_deleted</type>
        </header>
        <body>
            <session_id>sess-001</session_id>
            <reason>cancelled</reason>
            <deleted_by>planner</deleted_by>
        </body>
    </message>"""
    return xml.encode("utf-8")


def _make_view_request_body(session_id: str | None = None) -> bytes:
    session_id_xml = f"<session_id>{session_id}</session_id>" if session_id else ""
    xml = f"""<message xmlns="urn:integration:planning:v1">
        <header>
            <message_id>msg-view-001</message_id>
            <timestamp>2026-05-15T09:00:00Z</timestamp>
            <source>frontend</source>
            <type>session_view_request</type>
            <correlation_id>corr-view-001</correlation_id>
        </header>
        <body>
            {session_id_xml}
        </body>
    </message>"""
    return xml.encode("utf-8")


class TestValidateXml:
    def setup_method(self):
        reset_sessions_store()

    def test_valid_message_returns_element(self):
        result = validate_xml(_make_valid_body())
        assert result is not None
        assert result.tag == "message"

    def test_malformed_xml_returns_none(self):
        assert validate_xml(b"<root><unclosed>") is None

    def test_missing_header_returns_none(self):
        xml = b"<message><body><session_id>x</session_id></body></message>"
        assert validate_xml(xml) is None

    def test_missing_body_returns_none(self):
        xml = b"<message><header><message_id>x</message_id><timestamp>x</timestamp><source>x</source><type>x</type></header></message>"
        assert validate_xml(xml) is None

    def test_missing_header_field_returns_none(self):
        # message_id is missing
        xml = b"""<message>
            <header>
                <timestamp>2026-05-15T09:00:00Z</timestamp>
                <source>calendar</source>
                <type>calendar.invite</type>
            </header>
            <body>
                <session_id>x</session_id><title>x</title>
                <start_datetime>x</start_datetime><end_datetime>x</end_datetime>
            </body>
        </message>"""
        assert validate_xml(xml) is None

    def test_missing_body_field_returns_none(self):
        # title is missing
        xml = b"""<message>
            <header>
                <message_id>x</message_id><timestamp>x</timestamp>
                <source>x</source><type>x</type>
            </header>
            <body>
                <session_id>x</session_id>
                <start_datetime>x</start_datetime><end_datetime>x</end_datetime>
            </body>
        </message>"""
        assert validate_xml(xml) is None

    def test_non_utf8_bytes_returns_none(self):
        assert validate_xml(b"\xff\xfe invalid") is None

    def test_session_updated_message_returns_element(self):
        result = validate_xml(_make_updated_body())
        assert result is not None

    def test_session_created_message_returns_element(self):
        result = validate_xml(_make_created_body())
        assert result is not None

    def test_session_deleted_message_returns_element(self):
        result = validate_xml(_make_deleted_body())
        assert result is not None

    def test_session_view_request_without_body_fields_returns_element(self):
        result = validate_xml(_make_view_request_body())
        assert result is not None

    def test_unsupported_type_returns_none(self):
        xml = b"""<message>
            <header>
                <message_id>x</message_id><timestamp>x</timestamp>
                <source>x</source><type>unknown_type</type>
            </header>
            <body><session_id>x</session_id></body>
        </message>"""
        assert validate_xml(xml) is None


class TestHandleCalendarInvite:
    def setup_method(self):
        reset_sessions_store()

    def test_logs_expected_fields(self, caplog):
        import logging
        root = validate_xml(_make_valid_body(
            message_id="msg-123",
            source="calendar",
            session_id="sess-abc",
            title="Keynote",
        ))
        with caplog.at_level(logging.INFO, logger="consumer"):
            handle_calendar_invite(root)

        assert "msg-123" in caplog.text
        assert "sess-abc" in caplog.text
        assert "Keynote" in caplog.text

    def test_missing_location_does_not_crash(self):
        xml = b"""<message>
            <header>
                <message_id>x</message_id><timestamp>x</timestamp>
                <source>calendar</source><type>calendar.invite</type>
            </header>
            <body>
                <session_id>s</session_id><title>t</title>
                <start_datetime>2026-01-01T00:00:00Z</start_datetime>
                <end_datetime>2026-01-01T01:00:00Z</end_datetime>
            </body>
        </message>"""
        root = etree.fromstring(xml)
        handle_calendar_invite(root)  # should not crash


class TestOnMessage:
    def setup_method(self):
        reset_sessions_store()

    def _make_method(self, routing_key="calendar.invite", delivery_tag=1):
        method = MagicMock()
        method.routing_key = routing_key
        method.delivery_tag = delivery_tag
        return method

    def test_valid_message_is_acked(self):
        channel = MagicMock()
        on_message(channel, self._make_method(), MagicMock(), _make_valid_body())
        channel.basic_ack.assert_called_once_with(delivery_tag=1)
        channel.basic_nack.assert_not_called()

    def test_invalid_message_is_nacked(self):
        channel = MagicMock()
        on_message(channel, self._make_method(), MagicMock(), b"<broken>")
        channel.basic_nack.assert_called_once_with(delivery_tag=1, requeue=False)
        channel.basic_ack.assert_not_called()

    def test_invalid_xml_is_logged(self, caplog):
        import logging
        channel = MagicMock()
        with caplog.at_level(logging.ERROR, logger="consumer"):
            on_message(channel, self._make_method(), MagicMock(), b"<broken>")
        assert "Invalid message" in caplog.text
        assert "<broken>" in caplog.text

    def test_updated_message_is_acked(self):
        channel = MagicMock()
        on_message(channel, self._make_method("planning.session.updated"), MagicMock(), _make_updated_body())
        channel.basic_ack.assert_called_once_with(delivery_tag=1)
        channel.basic_nack.assert_not_called()

    def test_deleted_message_is_acked(self):
        channel = MagicMock()
        on_message(channel, self._make_method("planning.session.deleted"), MagicMock(), _make_deleted_body())
        channel.basic_ack.assert_called_once_with(delivery_tag=1)
        channel.basic_nack.assert_not_called()

    def test_created_then_updated_then_deleted_changes_read_model(self):
        channel = MagicMock()

        on_message(channel, self._make_method("planning.session.created"), MagicMock(), _make_created_body())
        assert get_session("sess-001") is not None
        assert get_session("sess-001")["title"] == "Created session"

        on_message(channel, self._make_method("planning.session.updated"), MagicMock(), _make_updated_body())
        assert get_session("sess-001")["title"] == "Updated session"

        on_message(channel, self._make_method("planning.session.deleted"), MagicMock(), _make_deleted_body())
        assert get_session("sess-001") is None

    def test_view_request_publishes_response_with_session(self):
        channel = MagicMock()

        on_message(channel, self._make_method("planning.session.created"), MagicMock(), _make_created_body())
        on_message(channel, self._make_method("planning.session.view.request"), MagicMock(), _make_view_request_body("sess-001"))

        assert channel.basic_publish.called
        response_xml = channel.basic_publish.call_args.kwargs["body"]
        response_root = _strip_ns(etree.fromstring(response_xml.encode("utf-8")))
        assert response_root.find("header").findtext("type") == "session_view_response"
        assert response_root.find("header").findtext("correlation_id") == "corr-view-001"
        assert response_root.find("body").findtext("status") == "ok"
        assert response_root.find("body").findtext("session_count") == "1"

    def test_view_request_for_missing_session_returns_not_found(self):
        channel = MagicMock()

        on_message(channel, self._make_method("planning.session.view.request"), MagicMock(), _make_view_request_body("missing-id"))

        response_xml = channel.basic_publish.call_args.kwargs["body"]
        response_root = _strip_ns(etree.fromstring(response_xml.encode("utf-8")))
        assert response_root.find("body").findtext("status") == "not_found"
        assert response_root.find("body").findtext("session_count") == "0"
