"""Deterministic identifiers for canonical course data.

Random IDs make two inspections of the same package produce unrelated canonical
graphs and make reports impossible to diff across runs.  Every identifier in the
IR is instead derived from a stable source key with UUIDv5, so the same source
content (and the same source path/identity) always produces the same IDs.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

# A fixed application namespace: changing this intentionally breaks ID
# compatibility and should coincide with a schema-version bump.
_ID_NAMESPACE = uuid.uuid5(
    uuid.NAMESPACE_URL, "https://github.com/Team-Delta/Team-Delta/lms-converter/ids/v1"
)


def stable_id(kind: str, *parts: Any) -> str:
    """Return a deterministic UUID string for a kind and source identity parts."""
    payload = "|".join([kind, *(str(part) for part in parts)])
    return str(uuid.uuid5(_ID_NAMESPACE, payload))


def sha256_bytes(data: bytes) -> str:
    """Return a lowercase SHA-256 digest for integrity tracking."""
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    """Return a lowercase SHA-256 digest for UTF-8 text."""
    return sha256_bytes(text.encode("utf-8"))
