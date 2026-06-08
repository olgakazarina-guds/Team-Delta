"""
Raw Fragment Entities – Source provenance tracking for course migration.

Tracks original source XML fragments for:
Auditing and debugging
Reconstructing original content
Linking canonical entities back to source files
"""

from pydantic import BaseModel
from typing import Optional

from .enums import FragmentKind, SourceSystem


class SourceLocation(BaseModel):
    """
    Location of a raw fragment in the source LMS package.

    Tracks where the fragment originated from for provenance and debugging.
    """

    source_system: SourceSystem
    package_path: Optional[str] = None  # Path relative to package root
    file_path: Optional[str] = None  # Absolute file path
    node_id: Optional[str] = None  # Node ID within the file
    xpath: Optional[str] = None  # XPath within XML file


class RawFragment(BaseModel):
    """
    Raw fragment of source content (XML, HTML, JSON, etc.).

    Stores original content from source LMS for auditing, debugging,
    and potential reconstruction of original format.
    """

    fragment_id: str
    kind: FragmentKind
    source_location: SourceLocation
    raw_text: Optional[str] = None  # Small text fragments (inline)
    raw_bytes_ref: Optional[str] = None  # File path for large/binary content
    checksum: Optional[str] = None  # SHA-1 or MD5 hash for integrity
