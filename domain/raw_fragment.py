from pydantic import BaseModel
from typing import Optional
from .enums import FragmentKind, SourceSystem

class SourceLocation(BaseModel):
    source_system: SourceSystem
    package_path: Optional[str] = None
    file_path: Optional[str] = None
    node_id: Optional[str] = None
    xpath: Optional[str] = None

class RawFragment(BaseModel):
    fragment_id: str
    kind: FragmentKind
    source_location: SourceLocation
    raw_text: Optional[str] = None          # small fragments
    raw_bytes_ref: Optional[str] = None     # local file path for large/binary
    checksum: Optional[str] = None
