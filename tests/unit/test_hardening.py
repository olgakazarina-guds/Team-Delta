from __future__ import annotations

import io
import stat
import tarfile
import zipfile
from pathlib import Path

import pytest

from adapters.openedx.course_parser import OpenEdxCourseParser
from core.archive_utils import safe_extract_tar, safe_extract_zip
from core.errors import ArchiveSecurityError, UnsafePathError, XmlSecurityError
from core.xml_utils import parse_xml_text


def test_zip_symlink_is_rejected(tmp_path: Path):
    archive_path = tmp_path / "link.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        info = zipfile.ZipInfo("link")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "target")

    with pytest.raises(ArchiveSecurityError):
        safe_extract_zip(archive_path, tmp_path / "out")


def test_tar_symlink_is_rejected(tmp_path: Path):
    archive_path = tmp_path / "link.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        info = tarfile.TarInfo("link")
        info.type = tarfile.SYMTYPE
        info.linkname = "target"
        archive.addfile(info)

    with pytest.raises(ArchiveSecurityError):
        safe_extract_tar(archive_path, tmp_path / "out")


def test_zip_compression_bomb_is_rejected(tmp_path: Path):
    archive_path = tmp_path / "bomb.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("zeros.bin", b"\x00" * (6 * 1024 * 1024))

    with pytest.raises(ArchiveSecurityError):
        safe_extract_zip(archive_path, tmp_path / "out")


def test_xml_entity_expansion_is_rejected():
    payload = """<!DOCTYPE lolz [
        <!ENTITY lol "lol">
    ]>
    <lolz>&lol;</lolz>"""

    with pytest.raises(XmlSecurityError):
        parse_xml_text(payload)


def test_xml_size_limit_is_enforced():
    with pytest.raises(XmlSecurityError):
        parse_xml_text("<root>" + ("x" * 100) + "</root>", max_bytes=16)


def test_openedx_course_url_name_traversal_is_rejected(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "course.xml").write_text(
        '<course url_name="../../escape" org="Org" course="Course" />',
        encoding="utf-8",
    )
    archive_path = tmp_path / "evil.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(source / "course.xml", arcname="course.xml")

    with pytest.raises(UnsafePathError):
        OpenEdxCourseParser().parse(str(archive_path), str(tmp_path / "work"))


def test_tar_traversal_is_still_rejected(tmp_path: Path):
    archive_path = tmp_path / "evil.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        data = b"oops"
        info = tarfile.TarInfo("../evil.txt")
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))

    with pytest.raises(ValueError):
        safe_extract_tar(archive_path, tmp_path / "out")
