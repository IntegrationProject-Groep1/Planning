import pytest
from unittest.mock import MagicMock, patch
from lxml import etree

from producer import create_session_xml, validate_xml, send_message


class TestCreateSessionXml:
    def test_returns_valid_xml(self):
        xml = create_session_xml(
            session_id="sess-001",
            title="Test sessie",
            start_datetime="2026-05-15T14:00:00Z",
            end_datetime="2026-05-15T15:00:00Z",
            location="online",
        )
        root = etree.fromstring(xml.encode())
        assert root.tag == "message"

    def test_required_header_fields(self):
        xml = create_session_xml(
            session_id="sess-001",
            title="Test",
            start_datetime="2026-05-15T14:00:00Z",
            end_datetime="2026-05-15T15:00:00Z",
            location="online",
        )
        root = etree.fromstring(xml.encode())
        header = root.find("header")
        assert header is not None
        for field in ("message_id", "timestamp", "source", "type", "version", "correlation_id"):
            assert header.find(field) is not None, f"Missing header field: {field}"

    def test_required_body_fields(self):
        xml = create_session_xml(
            session_id="sess-001",
            title="Test",
            start_datetime="2026-05-15T14:00:00Z",
            end_datetime="2026-05-15T15:00:00Z",
            location="online",
        )
        root = etree.fromstring(xml.encode())
        body = root.find("body")
        assert body is not None
        for field in ("session_id", "title", "start_datetime", "end_datetime", "location", "session_type", "status", "max_attendees", "current_attendees"):
            assert body.find(field) is not None, f"Missing body field: {field}"

    def test_field_values(self):
        xml = create_session_xml(
            session_id="sess-001",
            title="Keynote",
            start_datetime="2026-05-15T14:00:00Z",
            end_datetime="2026-05-15T15:00:00Z",
            location="online",
            max_attendees=50,
        )
        root = etree.fromstring(xml.encode())
        body = root.find("body")
        assert body.findtext("session_id") == "sess-001"
        assert body.findtext("title") == "Keynote"
        assert body.findtext("max_attendees") == "50"

    def test_source_is_planning(self):
        xml = create_session_xml(
            session_id="x", title="x",
            start_datetime="2026-01-01T00:00:00Z",
            end_datetime="2026-01-01T01:00:00Z",
            location="x",
        )
        root = etree.fromstring(xml.encode())
        assert root.find("header").findtext("source") == "planning"

    def test_snake_case_field_names(self):
        xml = create_session_xml(
            session_id="x", title="x",
            start_datetime="2026-01-01T00:00:00Z",
            end_datetime="2026-01-01T01:00:00Z",
            location="x",
        )
        # Ensure no camelCase field names are present
        for elem in etree.fromstring(xml.encode()).iter():
            assert elem.tag == elem.tag.lower() or "_" in elem.tag or elem.tag == "message", \
                f"camelCase tag gevonden: {elem.tag}"


class TestValidateXml:
    def test_valid_xml_returns_true(self):
        assert validate_xml("<root><child/></root>") is True

    def test_malformed_xml_returns_false(self):
        assert validate_xml("<root><unclosed>") is False

    def test_empty_string_returns_false(self):
        assert validate_xml("") is False


class TestSendMessage:
    def _make_valid_xml(self):
        return create_session_xml(
            session_id="sess-001",
            title="Test",
            start_datetime="2026-05-15T14:00:00Z",
            end_datetime="2026-05-15T15:00:00Z",
            location="online",
        )

    @patch("producer.pika.BlockingConnection")
    @patch.dict("os.environ", {"RABBITMQ_USER": "user", "RABBITMQ_PASS": "pass"})
    def test_send_valid_message_returns_true(self, mock_conn_cls):
        mock_channel = MagicMock()
        mock_conn_cls.return_value.channel.return_value = mock_channel

        result = send_message(self._make_valid_xml())

        assert result is True
        mock_channel.basic_publish.assert_called_once()

    @patch("producer.pika.BlockingConnection")
    @patch.dict("os.environ", {"RABBITMQ_USER": "user", "RABBITMQ_PASS": "pass"})
    def test_send_invalid_xml_returns_false(self, mock_conn_cls):
        mock_conn_cls.return_value.channel.return_value = MagicMock()

        result = send_message("<broken>")

        assert result is False

    @patch("producer.pika.BlockingConnection", side_effect=Exception("verbindingsfout"))
    @patch.dict("os.environ", {"RABBITMQ_USER": "user", "RABBITMQ_PASS": "pass"})
    def test_connection_error_returns_false(self, _mock_conn):
        result = send_message(self._make_valid_xml())
        assert result is False

    @patch.dict("os.environ", {"RABBITMQ_USER": "", "RABBITMQ_PASS": ""})
    def test_missing_credentials_returns_false(self):
        import producer as p
        p.RABBITMQ_USER = None
        p.RABBITMQ_PASS = None
        result = send_message(self._make_valid_xml())
        assert result is False
