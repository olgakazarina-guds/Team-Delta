"""Helpers for extracting archives without allowing path traversal."""

from __future__ import annotations

import tarfile
import zipfile
from pathlib import Path, PurePosixPath


def _safe_member_path(base: Path, name: str) -> Path:
    """Resolve an archive member name below ``base`` or raise ``ValueError``."""
    member = PurePosixPath(name)
    if member.is_absolute() or ".." in member.parts:
        raise ValueError(f"Unsafe archive member path: {name!r}")

    destination = (base / member).resolve()
    try:
        destination.relative_to(base.resolve())
    except ValueError as exc:
        raise ValueError(f"Archive member escapes target directory: {name!r}") from exc
    return destination


def safe_extract_tar(archive_path: str | Path, target_dir: str | Path) -> None:
    """Extract a tar archive, rejecting traversal, links, and device files."""
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)

    with tarfile.open(archive_path, "r:*") as archive:
        members = []
        for member in archive.getmembers():
            _safe_member_path(target, member.name)
            if member.issym() or member.islnk():
                raise ValueError(f"Archive contains a link: {member.name!r}")
            if member.isdev():
                raise ValueError(f"Archive contains a device entry: {member.name!r}")
            members.append(member)
        archive.extractall(target, members=members, filter="data")


def safe_extract_zip(archive_path: str | Path, target_dir: str | Path) -> None:
    """Extract a zip archive, rejecting traversal and absolute paths."""
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(archive_path, "r") as archive:
        for name in archive.namelist():
            _safe_member_path(target, name)
        archive.extractall(target)


def resolve_under(base: str | Path, relative_path: str | Path) -> Path:
    """Resolve ``relative_path`` under ``base`` and reject traversal."""
    base_path = Path(base).resolve()
    candidate = (base_path / relative_path).resolve()
    try:
        candidate.relative_to(base_path)
    except ValueError as exc:
        raise ValueError(f"Path escapes base directory: {relative_path!r}") from exc
    return candidate
