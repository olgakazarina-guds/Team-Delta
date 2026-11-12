"""Hardened XML parsing helpers.

All untrusted package XML must go through this module.  ``defusedxml`` disables
DTD entity expansion and external entity resolution; the byte limit prevents a
single oversized document from exhausting memory.  XML *generation* continues to
use the standard-library ElementTree because output is application-controlled.
"""

from __future__ import annotations

from pathlib import Path

# Types and error passthrough only; untrusted parsing uses defusedxml.
from xml.etree.ElementTree import Element, ParseError  # nosec B405

from defusedxml import ElementTree as DefusedElementTree
from defusedxml.common import DefusedXmlException

from core.config import get_settings
from core.errors import XmlSecurityError


def _max_bytes() -> int:
    """Resolve the configured XML limit without importing config at module load."""
    return get_settings().max_xml_bytes


def _max_depth() -> int:
    """Resolve the configured XML nesting limit."""
    return get_settings().max_xml_depth


def _check_depth(root: Element, limit: int, source: str) -> None:
    """Reject trees deeper than ``limit`` without recursive traversal."""
    stack: list[tuple[Element, int]] = [(root, 1)]
    while stack:
        node, depth = stack.pop()
        if depth > limit:
            raise XmlSecurityError(f"XML nesting exceeds {limit} levels: {source!r}")
        stack.extend((child, depth + 1) for child in node)


def parse_xml_bytes(
    data: bytes,
    *,
    source: str = "<memory>",
    max_bytes: int | None = None,
    max_depth: int | None = None,
) -> Element:
    """Parse untrusted XML bytes with entity, size, and nesting protections."""
    limit = max_bytes if max_bytes is not None else _max_bytes()
    if len(data) > limit:
        raise XmlSecurityError(
            f"XML document exceeds {limit} bytes: {source!r} ({len(data)} bytes)"
        )
    try:
        root = DefusedElementTree.fromstring(data)
    except DefusedXmlException as exc:
        raise XmlSecurityError(f"Unsafe XML in {source!r}: {exc}") from exc
    except ParseError:
        raise
    except Exception as exc:  # pragma: no cover - defensive for parser variants
        raise XmlSecurityError(f"Could not safely parse XML {source!r}: {exc}") from exc
    _check_depth(root, max_depth if max_depth is not None else _max_depth(), source)
    return root


def parse_xml_text(
    text: str,
    *,
    source: str = "<string>",
    max_bytes: int | None = None,
    max_depth: int | None = None,
) -> Element:
    """Parse untrusted XML text with the same protections as :func:`parse_xml_bytes`."""
    return parse_xml_bytes(
        text.encode("utf-8"),
        source=source,
        max_bytes=max_bytes,
        max_depth=max_depth,
    )


def parse_xml_file(
    path: str | Path,
    *,
    max_bytes: int | None = None,
    max_depth: int | None = None,
) -> Element:
    """Read and safely parse an XML file, checking size before loading it."""
    xml_path = Path(path)
    limit = max_bytes if max_bytes is not None else _max_bytes()
    try:
        size = xml_path.stat().st_size
    except OSError:
        raise
    if size > limit:
        raise XmlSecurityError(f"XML file exceeds {limit} bytes: {str(xml_path)!r} ({size} bytes)")
    return parse_xml_bytes(
        xml_path.read_bytes(),
        source=str(xml_path),
        max_bytes=limit,
        max_depth=max_depth,
    )
