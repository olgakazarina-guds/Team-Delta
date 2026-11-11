import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional

DB_PATH = Path("data/lms_converter.db")


def init_db() -> None:
    """Create the jobs table if it does not exist."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            source_type TEXT,
            target_type TEXT,
            course_json TEXT,
            report_json TEXT,
            extracted_path TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def _serialize_course(course: Any) -> str:
    if hasattr(course, "model_dump_json"):
        return course.model_dump_json()
    if hasattr(course, "dict"):
        return json.dumps(course.dict())
    return json.dumps(course)


def _serialize_report(report: list) -> str:
    return json.dumps(
        [
            item.model_dump() if hasattr(item, "model_dump") else item
            for item in report
        ]
    )


def save_job(
    job_id: str,
    source_type: str,
    target_type: str,
    course: Any,
    report: list,
    extracted_path: Optional[str] = None,
) -> None:
    """Save a fresh inspection job."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        INSERT OR REPLACE INTO jobs
            (job_id, source_type, target_type, course_json, report_json, extracted_path)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            job_id,
            source_type,
            "",
            _serialize_course(course),
            _serialize_report(report),
            extracted_path,
        ),
    )
    conn.commit()
    conn.close()


def save_migration_job(
    job_id: str,
    source_type: str,
    target_type: str,
    course: Any,
    report: list,
    extracted_path: Optional[str] = None,
) -> None:
    """Update an existing job with migration details without losing its report."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT course_json, report_json, extracted_path FROM jobs WHERE job_id = ?",
        (job_id,),
    )
    existing = c.fetchone()

    course_json = _serialize_course(course)
    report_json = _serialize_report(report) if report else None
    if existing:
        existing_course, existing_report, existing_extracted = existing
        if not course_json:
            course_json = existing_course
        if report_json is None:
            report_json = existing_report or "[]"
        if not extracted_path:
            extracted_path = existing_extracted

    c.execute(
        """
        INSERT INTO jobs
            (job_id, source_type, target_type, course_json, report_json, extracted_path)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(job_id) DO UPDATE SET
            source_type = excluded.source_type,
            target_type = excluded.target_type,
            course_json = excluded.course_json,
            report_json = excluded.report_json,
            extracted_path = excluded.extracted_path
        """,
        (
            job_id,
            source_type,
            target_type,
            course_json,
            report_json or "[]",
            extracted_path,
        ),
    )
    conn.commit()
    conn.close()


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a job by ID."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT job_id, source_type, target_type, course_json, report_json, "
        "extracted_path, created_at FROM jobs WHERE job_id = ?",
        (job_id,),
    )
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "job_id": row[0],
        "source_type": row[1],
        "target_type": row[2],
        "course_json": row[3],
        "report_json": row[4],
        "extracted_path": row[5],
        "created_at": row[6],
    }
