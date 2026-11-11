"""Helpers for extracting untrusted archives safely.

The extractors enforce four boundaries before a single byte is written:

* no absolute paths, ``..`` traversal, or backslash ambiguity;
* no symbolic links, hard links, devices, or FIFOs;
* bounded entry counts and uncompressed sizes;
* bounded compression ratios (zip-slip / decompression-bomb defence).

Limits are intentionally conservative and can be adjusted per deployment with
``ExtractionLimits`` while retaining the same API.
"""

from __future__ import annotations

import stat
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from core.errors import ArchiveSecurityError, UnsafePathError


@dataclass(frozen=True)
class ExtractionLimits:
    """Resource and shape limits applied to one archive extraction."""

    max_entries: int = 50_000
    max_total_bytes: int = 2 * 1024 * 1024 * 1024  # 2 GiB
    max_member_bytes: int = 512 * 1024 * 1024  # 512 MiB
    max_compression_ratio: float = 250.0
    ratio_check_min_bytes: int = 5 * 1024 * 1024  # avoid false positives


def _safe_member_path(base: Path, name: str) -> Path:
    """Resolve an archive member name below ``base`` or raise ``UnsafePathError``."""
    if not name or "\x00" in name or "\\" in name:
        raise UnsafePathError(f"Unsafe archive member path: {name!r}")

    member = PurePosixPath(name)
    if member.is_absolute() or ".." in member.parts:
        raise UnsafePathError(f"Unsafe archive member path: {name!r}")

    try:
        destination = (base / member).resolve()
        destination.relative_to(base.resolve())
    except (OSError, ValueError) as exc:
        raise UnsafePathError(f"Archive member escapes target directory: {name!r}") from exc
    return destination


def _check_ratio(
    *,
    name: str,
    uncompressed_size: int,
    compressed_size: int,
    limits: ExtractionLimits,
) -> None:
    if (
        uncompressed_size >= limits.ratio_check_min_bytes
        and compressed_size > 0
        and uncompressed_size / compressed_size > limits.max_compression_ratio
    ):
        raise ArchiveSecurityError(
            f"Suspicious compression ratio for {name!r}: "
            f"{uncompressed_size} bytes from {compressed_size} bytes"
        )


def safe_extract_tar(
    archive_path: str | Path,
    target_dir: str | Path,
    *,
    limits: ExtractionLimits | None = None,
) -> None:
    """Extract a tar archive after validating every member and global budget."""
    cfg = limits or ExtractionLimits()
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    archive_size = Path(archive_path).stat().st_size

    with tarfile.open(archive_path, "r:*") as archive:
        members = archive.getmembers()
        if len(members) > cfg.max_entries:
            raise ArchiveSecurityError(
                f"Archive has {len(members)} entries; limit is {cfg.max_entries}"
            )

        total_bytes = 0
        for member in members:
            _safe_member_path(target, member.name)
            if member.issym() or member.islnk():
                raise ArchiveSecurityError(f"Archive contains a link: {member.name!r}")
            if member.isdev() or member.isfifo():
                raise ArchiveSecurityError(
                    f"Archive contains a special entry: {member.name!r}"
                )
            if not (member.isreg() or member.isdir()):
                raise ArchiveSecurityError(
                    f"Archive contains an unsupported entry: {member.name!r}"
                )

            size = max(member.size, 0)
            if size > cfg.max_member_bytes:
                raise ArchiveSecurityError(
                    f"Archive member {member.name!r} is {size} bytes; "
                    f"limit is {cfg.max_member_bytes}"
                )
            total_bytes += size
            if total_bytes > cfg.max_total_bytes:
                raise ArchiveSecurityError(
                    f"Archive expands to more than {cfg.max_total_bytes} bytes"
                )

        _check_ratio(
            name=str(archive_path),
            uncompressed_size=total_bytes,
            compressed_size=archive_size,
            limits=cfg,
        )
        archive.extractall(target, members=members, filter="data")


def safe_extract_zip(
    archive_path: str | Path,
    target_dir: str | Path,
    *,
    limits: ExtractionLimits | None = None,
) -> None:
    """Extract a zip archive after validating members, links, and size budgets."""
    cfg = limits or ExtractionLimits()
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(archive_path, "r") as archive:
        infos = archive.infolist()
        if len(infos) > cfg.max_entries:
            raise ArchiveSecurityError(
                f"Archive has {len(infos)} entries; limit is {cfg.max_entries}"
            )

        seen: set[str] = set()
        total_bytes = 0
        for info in infos:
            if info.filename in seen:
                raise ArchiveSecurityError(
                    f"Archive contains duplicate entry: {info.filename!r}"
                )
            seen.add(info.filename)
            _safe_member_path(target, info.filename)

            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ArchiveSecurityError(
                    f"Archive contains a symbolic link: {info.filename!r}"
                )
            if info.flag_bits & 0x1:
                raise ArchiveSecurityError(
                    f"Encrypted archive member is not supported: {info.filename!r}"
                )

            size = info.file_size
            if size > cfg.max_member_bytes:
                raise ArchiveSecurityError(
                    f"Archive member {info.filename!r} is {size} bytes; "
                    f"limit is {cfg.max_member_bytes}"
                )
            total_bytes += size
            if total_bytes > cfg.max_total_bytes:
                raise ArchiveSecurityError(
                    f"Archive expands to more than {cfg.max_total_bytes} bytes"
                )
            _check_ratio(
                name=info.filename,
                uncompressed_size=size,
                compressed_size=info.compress_size,
                limits=cfg,
            )

        archive.extractall(target)


def resolve_under(base: str | Path, relative_path: str | Path) -> Path:
    """Resolve ``relative_path`` under ``base`` and reject traversal.

    ``..`` is rejected even when it would resolve back inside the root.  A
    resolved symlink is also rejected when its target is outside the root.
    """
    base_path = Path(base).resolve()
    raw = str(relative_path)
    if not raw or "\x00" in raw:
        raise UnsafePathError(f"Invalid relative path: {relative_path!r}")

    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise UnsafePathError(f"Path escapes base directory: {relative_path!r}")

    try:
        candidate = (base_path / relative).resolve()
        candidate.relative_to(base_path)
    except (OSError, ValueError) as exc:
        raise UnsafePathError(f"Path escapes base directory: {relative_path!r}") from exc
    return candidate
