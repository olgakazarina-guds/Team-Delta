"""Hardened XML parsing helpers.

All untrusted package XML must go through this module.  ``defusedxml`` disables
DTD entity expansion and external entity resolution; the byte limit prevents a
single oversized document from exhausting memory.  XML *generation* continues to
use the standard-library ElementTree because output is application-controlled.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

from defusedxml import ElementTree as DefusedElementTree
from defusedxml.common import DefusedXmlException
from xml.etree.ElementTree import Element, ParseError

from core.errors import XmlSecurityError

DEFAULT_MAX_XML_BYTES: Final[int] = 64 * 1024 * 1024


def _max_bytes() -> int:
    """Allow deployments to lower/raise the XML limit without code changes."""
    raw = os.environ.get("LMS_CONVERTER_MAX_XML_BYTES")
    if not raw:
        return DEFAULT_MAX_XML_BYTES
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_XML_BYTES
    return value if value > 0 else DEFAULT_MAX_XML_BYTES


def parse_xml_bytes(
    data: bytes,
    *,
    source: str = "<memory>",
    max_bytes: int | None = None,
) -> Element:
    """Parse untrusted XML bytes with entity and size protections."""
    limit = max_bytes if max_bytes is not None else _max_bytes()
    if len(data) > limit:
        raise XmlSecurityError(
            f"XML document exceeds {limit} bytes: {source!r} ({len(data)} bytes)"
        )
    try:
        return DefusedElementTree.fromstring(data)
    except DefusedXmlException as exc:
        raise XmlSecurityError(f"Unsafe XML in {source!r}: {exc}") from exc
    except ParseError:
        raise
    except Exception as exc:  # pragma: no cover - defensive for parser variants
        raise XmlSecurityError(f"Could not safely parse XML {source!r}: {exc}") from exc


def parse_xml_text(
    text: str,
    *,
    source: str = "<string>",
    max_bytes: int | None = None,
) -> Element:
    """Parse untrusted XML text with the same protections as :func:`parse_xml_bytes`."""
    return parse_xml_bytes(text.encode("utf-8"), source=source, max_bytes=max_bytes)


def parse_xml_file(
    path: str | Path,
    *,
    max_bytes: int | None = None,
) -> Element:
    """Read and safely parse an XML file, checking size before loading it."""
    xml_path = Path(path)
    limit = max_bytes if max_bytes is not None else _max_bytes()
    try:
        size = xml_path.stat().st_size
    except OSError:
        raise
    if size > limit:
        raise XmlSecurityError(
            f"XML file exceeds {limit} bytes: {str(xml_path)!r} ({size} bytes)"
        )
    return parse_xml_bytes(
        xml_path.read_bytes(),
        source=str(xml_path),
        max_bytes=limit,
    )
