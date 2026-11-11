from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from core.archive_utils import safe_extract_tar, safe_extract_zip


def test_tar_traversal_is_rejected(tmp_path: Path):
    archive_path = tmp_path / "evil.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        data = b"oops"
        info = tarfile.TarInfo("../evil.txt")
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))

    with pytest.raises(ValueError):
        safe_extract_tar(archive_path, tmp_path / "out")


def test_zip_traversal_is_rejected(tmp_path: Path):
    archive_path = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../evil.txt", "oops")

    with pytest.raises(ValueError):
        safe_extract_zip(archive_path, tmp_path / "out")
