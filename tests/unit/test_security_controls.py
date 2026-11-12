from __future__ import annotations

import hashlib
import io
import os
import tarfile
import time
import warnings
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from core.archive_utils import ExtractionLimits, safe_extract_tar, safe_extract_zip
from core.auth import require_identity
from core.config import Settings
from core.errors import (
    ArchiveSecurityError,
    AuthenticationError,
    UnsafePathError,
    UploadSecurityError,
    XmlSecurityError,
)
from core.outputs import resolve_output_path
from core.uploads import cleanup_expired_uploads, save_upload
from core.xml_utils import parse_xml_text


def _settings(tmp_path: Path) -> Settings:
    return Settings.from_env(data_dir=tmp_path)


def test_xml_depth_limit_is_enforced():
    payload = "<a>" * 6 + "</a>" * 6

    with pytest.raises(XmlSecurityError):
        parse_xml_text(payload, max_depth=3)


def test_tar_duplicate_entry_is_rejected(tmp_path: Path):
    archive_path = tmp_path / "duplicate.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        for _ in range(2):
            data = b"same"
            info = tarfile.TarInfo("same.txt")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))

    with pytest.raises(ArchiveSecurityError):
        safe_extract_tar(archive_path, tmp_path / "out")


def test_tar_normalized_duplicate_is_rejected(tmp_path: Path):
    archive_path = tmp_path / "alias.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        for name in ("same.txt", "./same.txt"):
            data = b"same"
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))

    with pytest.raises(ArchiveSecurityError):
        safe_extract_tar(archive_path, tmp_path / "out")


def test_tar_device_entry_is_rejected(tmp_path: Path):
    archive_path = tmp_path / "device.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        info = tarfile.TarInfo("device")
        info.type = tarfile.CHRTYPE
        archive.addfile(info)

    with pytest.raises(ArchiveSecurityError):
        safe_extract_tar(archive_path, tmp_path / "out")


def test_zip_normalized_duplicate_is_rejected(tmp_path: Path):
    archive_path = tmp_path / "alias.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("same.txt", "one")
        archive.writestr("./same.txt", "two")

    with pytest.raises(ArchiveSecurityError):
        safe_extract_zip(archive_path, tmp_path / "out")


def test_zip_total_compression_ratio_is_rejected(tmp_path: Path):
    archive_path = tmp_path / "bomb.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index in range(6):
            archive.writestr(f"chunk-{index}.bin", b"\0" * (1024 * 1024))

    with pytest.raises(ArchiveSecurityError):
        safe_extract_zip(archive_path, tmp_path / "out")


def test_zip_backslash_path_is_rejected(tmp_path: Path):
    archive_path = tmp_path / "backslash.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("..\\evil.txt", "oops")

    with pytest.raises(UnsafePathError):
        safe_extract_zip(archive_path, tmp_path / "out")


def test_encrypted_zip_entry_is_rejected(tmp_path: Path):
    archive_path = tmp_path / "encrypted.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("secret.txt", "hidden")

    data = bytearray(archive_path.read_bytes())
    data[6:8] = (1).to_bytes(2, "little")
    central = data.find(b"PK\x01\x02")
    data[central + 8 : central + 10] = (1).to_bytes(2, "little")
    archive_path.write_bytes(data)

    with pytest.raises(ArchiveSecurityError):
        safe_extract_zip(archive_path, tmp_path / "out")


def test_zip_duplicate_entry_is_rejected(tmp_path: Path):
    archive_path = tmp_path / "duplicate.zip"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("same.txt", "one")
            archive.writestr("same.txt", "two")

    with pytest.raises(ArchiveSecurityError):
        safe_extract_zip(archive_path, tmp_path / "out")


def test_archive_entry_and_size_limits_are_enforced(tmp_path: Path):
    archive_path = tmp_path / "two.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("one.txt", "one")
        archive.writestr("two.txt", "two")

    with pytest.raises(ArchiveSecurityError):
        safe_extract_zip(
            archive_path,
            tmp_path / "out",
            limits=ExtractionLimits(max_entries=1),
        )
    with pytest.raises(ArchiveSecurityError):
        safe_extract_zip(
            archive_path,
            tmp_path / "out",
            limits=ExtractionLimits(max_total_bytes=4),
        )


def test_upload_streams_hashes_and_stores_under_session(tmp_path: Path):
    settings = _settings(tmp_path)
    content = b"course bytes"

    stored = save_upload(
        io.BytesIO(content),
        "course.mbz",
        session_id="../../untrusted",
        settings=settings,
    )

    assert stored.size == len(content)
    assert stored.sha256 == hashlib.sha256(content).hexdigest()
    assert stored.path.read_bytes() == content
    assert stored.path.is_relative_to(settings.upload_dir)
    assert stored.session_dir.is_relative_to(settings.upload_dir)


def test_upload_rejects_oversize_and_removes_partial_file(tmp_path: Path):
    settings = replace(_settings(tmp_path), max_upload_bytes=4)

    with pytest.raises(UploadSecurityError):
        save_upload(
            io.BytesIO(b"12345"),
            "course.mbz",
            session_id="session",
            settings=settings,
        )

    assert not list(settings.upload_dir.rglob("*.mbz"))


def test_upload_rejects_empty_file(tmp_path: Path):
    with pytest.raises(UploadSecurityError):
        save_upload(
            io.BytesIO(b""),
            "course.mbz",
            session_id="session",
            settings=_settings(tmp_path),
        )


def test_upload_rejects_unknown_suffix(tmp_path: Path):
    with pytest.raises(UploadSecurityError):
        save_upload(
            io.BytesIO(b"data"),
            "course.txt",
            session_id="session",
            settings=_settings(tmp_path),
        )


def test_expired_upload_sessions_are_cleaned(tmp_path: Path):
    settings = _settings(tmp_path)
    settings.ensure_directories()
    old_dir = settings.upload_dir / "old"
    fresh_dir = settings.upload_dir / "fresh"
    old_dir.mkdir()
    fresh_dir.mkdir()
    old_time = time.time() - 7200
    os.utime(old_dir, (old_time, old_time))

    removed = cleanup_expired_uploads(settings, max_age_seconds=3600, now=time.time())

    assert removed == 1
    assert not old_dir.exists()
    assert fresh_dir.exists()


def test_output_path_stays_inside_server_root(tmp_path: Path):
    root = tmp_path / "out"
    path = resolve_output_path("course.tar.gz", root=root)

    assert path == root / "course.tar.gz"
    for bad in ("../escape.tar.gz", "/etc/passwd", "sub/course.tar.gz", "course.txt"):
        with pytest.raises(UnsafePathError):
            resolve_output_path(bad, root=root)


def test_auth_fails_closed_in_production(tmp_path: Path):
    production = replace(_settings(tmp_path), environment="production")
    with pytest.raises(AuthenticationError):
        require_identity(production, headers={})

    proxied = replace(
        production,
        auth_mode="proxy",
        trusted_user_header="X-Forwarded-User",
    )
    identity = require_identity(proxied, headers={"x-forwarded-user": "alice"})
    assert identity.user_id == "alice"
    assert identity.mode == "proxy"

    with pytest.raises(AuthenticationError):
        require_identity(proxied, headers={})


def test_auth_allows_local_identity_in_development(tmp_path: Path):
    identity = require_identity(_settings(tmp_path), headers={})

    assert identity.user_id == "local"
    assert identity.mode == "none"
