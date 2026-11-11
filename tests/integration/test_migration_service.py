from pathlib import Path

import pytest

from core.errors import JobAccessError
from core.ingest import IngestService
from core.migrate import MigrationService
from persistence.repositories import get_job


def _inspect(archive: Path, source_type: str, owner: str = "alice") -> dict:
    return IngestService(owner=owner).inspect(
        str(archive), source_type=source_type
    )


def test_migrate_openedx_to_moodle_updates_job(
    openedx_archive: Path, tmp_path: Path
):
    inspected = _inspect(openedx_archive, "openedx")
    output = tmp_path / "converted.mbz"

    migrated_path = MigrationService(owner="alice").migrate_to_moodle(
        inspected["course"],
        str(output),
        source_extracted_path=inspected["extracted_path"],
        job_id=inspected["job_id"],
        report=inspected["report"],
    )

    job = get_job(inspected["job_id"], owner="alice")
    assert job is not None
    assert Path(migrated_path) == output
    assert output.is_file()
    assert job["status"] == "migrated"
    assert job["target_type"] == "moodle"
    assert job["output_path"] == str(output)
    assert job["error"] is None


def test_migrate_moodle_to_openedx_updates_job(
    moodle_archive: Path, tmp_path: Path
):
    inspected = _inspect(moodle_archive, "moodle")
    output = tmp_path / "converted.tar.gz"

    migrated_path = MigrationService(owner="alice").migrate_to_openedx(
        inspected["course"],
        str(output),
        source_extracted_path=inspected["extracted_path"],
        job_id=inspected["job_id"],
        report=inspected["report"],
    )

    job = get_job(inspected["job_id"], owner="alice")
    assert job is not None
    assert Path(migrated_path) == output
    assert output.is_file()
    assert job["status"] == "migrated"
    assert job["target_type"] == "openedx"
    assert job["output_path"] == str(output)
    assert job["error"] is None


def test_migration_preserves_existing_report_when_none_supplied(
    openedx_archive: Path, tmp_path: Path
):
    inspected = _inspect(openedx_archive, "openedx")
    before = get_job(inspected["job_id"], owner="alice")

    MigrationService(owner="alice").migrate_to_moodle(
        inspected["course"],
        str(tmp_path / "converted.mbz"),
        source_extracted_path=inspected["extracted_path"],
        job_id=inspected["job_id"],
        report=[],
    )

    after = get_job(inspected["job_id"], owner="alice")
    assert before is not None and after is not None
    assert after["report_json"] == before["report_json"]


def test_migration_marks_job_failed_when_target_adapter_raises(
    openedx_archive: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    inspected = _inspect(openedx_archive, "openedx")
    service = MigrationService(owner="alice")

    def fail_generation(*args, **kwargs):
        raise RuntimeError("target adapter exploded")

    monkeypatch.setattr(service.moodle_target, "generate_backup", fail_generation)

    with pytest.raises(RuntimeError, match="target adapter exploded"):
        service.migrate_to_moodle(
            inspected["course"],
            str(tmp_path / "converted.mbz"),
            source_extracted_path=inspected["extracted_path"],
            job_id=inspected["job_id"],
        )

    job = get_job(inspected["job_id"], owner="alice")
    assert job is not None
    assert job["status"] == "failed"
    assert "RuntimeError: target adapter exploded" in job["error"]


def test_migration_rejects_job_owned_by_another_user(
    openedx_archive: Path, tmp_path: Path
):
    inspected = _inspect(openedx_archive, "openedx", owner="alice")

    with pytest.raises(JobAccessError):
        MigrationService(owner="bob").migrate_to_moodle(
            inspected["course"],
            str(tmp_path / "converted.mbz"),
            source_extracted_path=inspected["extracted_path"],
            job_id=inspected["job_id"],
        )

    assert get_job(inspected["job_id"], owner="bob") is None
    job = get_job(inspected["job_id"], owner="alice")
    assert job is not None
    assert job["status"] == "inspected"
