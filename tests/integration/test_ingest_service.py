import tarfile
from pathlib import Path

import pytest

from core.config import get_settings
from core.errors import UnsupportedSourceError
from core.ingest import IngestService
from persistence.repositories import get_job, list_jobs


def test_openedx_ingest_persists_course_owner_and_paths(openedx_archive: Path):
    result = IngestService(owner="alice").inspect(
        str(openedx_archive), source_type="openedx"
    )

    job = get_job(result["job_id"], owner="alice")
    assert job is not None
    assert job["owner"] == "alice"
    assert job["source_type"] == "openedx"
    assert job["target_type"] == ""
    assert job["status"] == "inspected"
    assert job["course_json"]
    assert job["report_json"] is not None

    extracted_path = Path(job["extracted_path"])
    assert extracted_path.is_relative_to(get_settings().work_dir)
    assert result["course"].source_system.value == "openedx"
    assert result["schema_version"]


def test_moodle_ingest_persists_course_owner_and_paths(moodle_archive: Path):
    result = IngestService(owner="bob").inspect(
        str(moodle_archive), source_type="moodle"
    )

    job = get_job(result["job_id"], owner="bob")
    assert job is not None
    assert job["owner"] == "bob"
    assert job["source_type"] == "moodle"
    assert job["status"] == "inspected"
    assert result["course"].source_system.value == "moodle"
    assert Path(job["extracted_path"]).is_relative_to(get_settings().work_dir)


def test_ingest_rejects_unknown_source_type_without_persisting(
    openedx_archive: Path,
):
    with pytest.raises(UnsupportedSourceError):
        IngestService(owner="alice").inspect(
            str(openedx_archive), source_type="canvas"
        )

    assert list_jobs(owner="alice") == []


def test_ingest_rejects_malformed_archive_without_persisting(tmp_path: Path):
    malformed = tmp_path / "malformed.tar.gz"
    malformed.write_bytes(b"this is not a tar archive")

    with pytest.raises(tarfile.TarError):
        IngestService(owner="alice").inspect(
            str(malformed), source_type="openedx"
        )

    assert list_jobs(owner="alice") == []
