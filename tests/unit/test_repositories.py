from __future__ import annotations

from domain.entities import Course, MappingNote
from domain.enums import Severity, SourceSystem
from persistence import repositories


def test_migration_job_preserves_report():
    course = Course(course_id="course-1", title="Course", source_system=SourceSystem.OPENEDX)
    report = [
        MappingNote(
            note_id="note-1",
            severity=Severity.WARNING,
            code="TEST",
            message="keep me",
        )
    ]

    repositories.save_job("job-1", "openedx", "", course, report)
    repositories.save_migration_job(
        "job-1", "openedx", "moodle", course, [], "/tmp/extract"
    )

    job = repositories.get_job("job-1")
    assert job is not None
    assert job["target_type"] == "moodle"
    assert "keep me" in job["report_json"]


def test_job_lifecycle_fields_are_persisted():
    course = Course(course_id="course-life", title="Life", source_system=SourceSystem.OPENEDX)
    repositories.save_job("job-life", "openedx", "moodle", course, [], "/tmp/x")

    job = repositories.get_job("job-life")
    assert job is not None
    assert job["target_type"] == "moodle"
    assert job["status"] == "inspected"

    repositories.save_migration_job(
        "job-life", "openedx", "moodle", course, [], "/tmp/x", "/tmp/out.mbz"
    )
    job = repositories.get_job("job-life")
    assert job is not None
    assert job["status"] == "migrated"
    assert job["output_path"] == "/tmp/out.mbz"
    assert job["updated_at"]
