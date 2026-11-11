"""Bounded, hash-addressed staging for untrusted course uploads."""

from __future__ import annotations

import hashlib
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterable

from core.config import Settings, get_settings
from core.errors import UploadSecurityError

DEFAULT_ALLOWED_SUFFIXES = (".mbz", ".tar.gz", ".tgz")
DEFAULT_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class StoredUpload:
    """A fully written upload with its integrity metadata."""

    path: Path
    sha256: str
    size: int
    session_dir: Path


def _suffix(filename: str, allowed: Iterable[str]) -> str:
    lowered = filename.lower()
    for suffix in allowed:
        if lowered.endswith(suffix):
            return suffix
    raise UploadSecurityError(
        f"Unsupported upload type: {filename!r}. Allowed: {', '.join(allowed)}"
    )


def _session_dir(settings: Settings, session_id: str) -> Path:
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:32]
    return settings.upload_dir / digest


def save_upload(
    source: BinaryIO,
    filename: str,
    *,
    session_id: str,
    settings: Settings | None = None,
    allowed_suffixes: Iterable[str] = DEFAULT_ALLOWED_SUFFIXES,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> StoredUpload:
    """Stream an upload to disk while enforcing the configured byte limit.

    Reads in bounded chunks instead of materialising the whole upload in memory,
    computes a SHA-256 digest, and stores the file in a per-session directory.
    """
    if not session_id:
        raise UploadSecurityError("An upload session identifier is required")

    cfg = settings or get_settings()
    allowed = tuple(allowed_suffixes)
    suffix = _suffix(filename, allowed)
    session_dir = _session_dir(cfg, session_id)
    session_dir.mkdir(parents=True, exist_ok=True)
    destination = session_dir / f"{uuid.uuid4().hex}{suffix}"

    digest = hashlib.sha256()
    total = 0
    try:
        with destination.open("wb") as target:
            while True:
                chunk = source.read(chunk_size)
                if not chunk:
                    break
                total += len(chunk)
                if total > cfg.max_upload_bytes:
                    raise UploadSecurityError(
                        f"Upload exceeds {cfg.max_upload_bytes} bytes"
                    )
                digest.update(chunk)
                target.write(chunk)
        if total == 0:
            raise UploadSecurityError("Upload is empty")
    except Exception:
        destination.unlink(missing_ok=True)
        raise

    return StoredUpload(
        path=destination,
        sha256=digest.hexdigest(),
        size=total,
        session_dir=session_dir,
    )


def cleanup_expired_uploads(
    settings: Settings | None = None,
    *,
    max_age_seconds: int | None = None,
    now: float | None = None,
) -> int:
    """Remove session directories older than the configured TTL.

    Returns the number of session directories removed.  Symlinks are ignored so
    cleanup cannot be redirected outside the upload root.
    """
    cfg = settings or get_settings()
    ttl = cfg.upload_ttl_seconds if max_age_seconds is None else max_age_seconds
    cutoff = (time.time() if now is None else now) - ttl
    removed = 0
    if not cfg.upload_dir.is_dir():
        return removed

    for entry in cfg.upload_dir.iterdir():
        try:
            if entry.is_symlink() or not entry.is_dir():
                continue
            if entry.stat().st_mtime >= cutoff:
                continue
            shutil.rmtree(entry)
            removed += 1
        except OSError:
            continue
    return removed
