import sqlite3

from core.config import get_settings
from persistence.repositories import get_job, init_db, list_jobs


def test_legacy_jobs_table_is_upgraded_without_data_loss():
    db_path = get_settings().db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE jobs (
                job_id TEXT PRIMARY KEY,
                source_type TEXT NOT NULL,
                target_type TEXT NOT NULL DEFAULT '',
                course_json TEXT,
                report_json TEXT,
                extracted_path TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            INSERT INTO jobs
                (job_id, source_type, target_type, course_json, report_json,
                 extracted_path)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-job",
                "openedx",
                "moodle",
                '{"title": "Legacy course"}',
                "[]",
                "/tmp/legacy",
            ),
        )
        conn.commit()

    init_db()

    job = get_job("legacy-job")
    assert job is not None
    assert job["course_json"] == '{"title": "Legacy course"}'
    assert job["target_type"] == "moodle"
    assert job["status"] == "inspected"
    assert job["owner"] == "local"
    assert job["output_path"] is None
    assert job["error"] is None
    assert job["updated_at"] is None

    assert [row["job_id"] for row in list_jobs()] == ["legacy-job"]


def test_init_db_is_idempotent():
    init_db()
    init_db()

    assert list_jobs() == []
