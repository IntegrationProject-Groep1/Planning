"""
XSD validation for outgoing (and optionally incoming) XML messages.
Uses lxml to validate against the XSD files in the schemas/ directory.
"""

import logging
import os
from typing import Optional

from lxml import etree

logger = logging.getLogger(__name__)

SCHEMAS_DIR = os.path.join(os.path.dirname(__file__), "schemas")

# Map message type values to XSD file names (without .xsd extension)
_SCHEMA_MAP: dict[str, str] = {
    "calendar.invite": "calendar_invite",
    "calendar.invite.confirmed": "calendar_invite_confirmed",
    "session_created": "session_created",
    "session_updated": "session_updated",
    "session_deleted": "session_deleted",
    "session_create_request": "session_create_request",
    "session_view_request": "session_view_request",
    "session_view_response": "session_view_response",
}

# Cache loaded schemas to avoid re-parsing on every call
_schema_cache: dict[str, etree.XMLSchema] = {}


def _load_schema(schema_name: str) -> etree.XMLSchema:
    """Load and cache an XSD schema by file name (without extension)."""
    if schema_name not in _schema_cache:
        path = os.path.join(SCHEMAS_DIR, f"{schema_name}.xsd")
        if not os.path.isfile(path):
            raise FileNotFoundError(f"XSD schema file not found: {path}")
        with open(path, "rb") as f:
            xsd_doc = etree.parse(f)
        _schema_cache[schema_name] = etree.XMLSchema(xsd_doc)
        logger.debug("Loaded XSD schema: %s", path)
    return _schema_cache[schema_name]


def validate_xml(xml_input: "str | bytes", message_type: str) -> tuple[bool, Optional[str]]:
    """
    Validate an XML document against its XSD schema.

    Args:
        xml_input: XML string or bytes to validate.
        message_type: Message type string (e.g. "session_created").

    Returns:
        (True, None) if valid.
        (False, error_message) if invalid or if the schema is unknown.
    """
    schema_name = _SCHEMA_MAP.get(message_type)
    if schema_name is None:
        msg = f"No XSD schema registered for message type: {message_type!r}"
        logger.warning(msg)
        return False, msg

    try:
        schema = _load_schema(schema_name)
        xml_bytes = xml_input.encode("utf-8") if isinstance(xml_input, str) else xml_input
        doc = etree.fromstring(xml_bytes)
        schema.assertValid(doc)
        logger.debug("XSD validation passed | message_type=%s", message_type)
        return True, None

    except etree.DocumentInvalid as exc:
        errors = "; ".join(str(e) for e in exc.error_log)
        logger.warning(
            "XSD validation failed | message_type=%s | errors=%s",
            message_type,
            errors,
        )
        return False, errors

    except FileNotFoundError as exc:
        logger.error("XSD schema file missing: %s", exc)
        return False, str(exc)

    except etree.XMLSyntaxError as exc:
        logger.error("Malformed XML passed to validator: %s", exc)
        return False, f"Malformed XML: {exc}"

    except Exception as exc:
        logger.error("Unexpected XSD validation error: %s", exc, exc_info=True)
        return False, f"Unexpected error: {exc}"


def validate_or_raise(xml_input: "str | bytes", message_type: str) -> None:
    """
    Validate XML and raise ValueError if invalid.
    Convenience wrapper for use inside builders/publishers.
    """
    valid, error = validate_xml(xml_input, message_type)
    if not valid:
        raise ValueError(
            f"XSD validation failed for {message_type!r}: {error}"
        )
