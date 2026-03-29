import pytest
from unittest.mock import MagicMock, patch
from lxml import etree

from consumer import validate_xml, handle_calendar_invite, on_message


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


class TestValidateXml:
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
        # message_id ontbreekt
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
        # title ontbreekt
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


class TestHandleCalendarInvite:
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
        handle_calendar_invite(root)  # mag niet crashen


class TestOnMessage:
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
        assert "Ongeldig bericht" in caplog.text
        assert "<broken>" in caplog.text
