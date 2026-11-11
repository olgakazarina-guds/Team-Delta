"""SQLite persistence for inspection and migration jobs.

The store is deliberately small but production-oriented: WAL mode, bounded
connection timeouts, transactional writes, forward-compatible schema upgrades,
and explicit lifecycle fields so operators can distinguish inspected,
migrated, and failed jobs.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

DB_PATH = Path(os.environ.get("LMS_CONVERTER_DB", "data/lms_converter.db"))

_REQUIRED_COLUMNS = {
    "status": "TEXT NOT NULL DEFAULT 'inspected'",
    "output_path": "TEXT",
    "error": "TEXT",
    "updated_at": "TIMESTAMP",
}


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    """Open a configured connection and always close it."""
    path = Path(DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        yield conn
    finally:
        conn.close()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            source_type TEXT NOT NULL,
            target_type TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'inspected',
            course_json TEXT,
            report_json TEXT,
            extracted_path TEXT,
            output_path TEXT,
            error TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    existing = {
        row["name"] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()
    }
    for name, definition in _REQUIRED_COLUMNS.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {name} {definition}")
    conn.commit()


def init_db() -> None:
    """Create or upgrade the jobs table."""
    with _connect() as conn:
        _ensure_schema(conn)


def _serialize_course(course: Any) -> str:
    if hasattr(course, "model_dump_json"):
        return course.model_dump_json()
    if hasattr(course, "dict"):
        return json.dumps(course.dict())
    return json.dumps(course)


def _serialize_report(report: list) -> str:
    items = []
    for item in report:
        if hasattr(item, "model_dump"):
            items.append(item.model_dump(mode="json"))
        else:
            items.append(item)
    return json.dumps(items)


def save_job(
    job_id: str,
    source_type: str,
    target_type: str,
    course: Any,
    report: list,
    extracted_path: Optional[str] = None,
    *,
    status: str = "inspected",
) -> None:
    """Save a newly inspected job and its canonical course snapshot."""
    init_db()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO jobs
                (job_id, source_type, target_type, status, course_json,
                 report_json, extracted_path, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(job_id) DO UPDATE SET
                source_type = excluded.source_type,
                target_type = excluded.target_type,
                status = excluded.status,
                course_json = excluded.course_json,
                report_json = excluded.report_json,
                extracted_path = excluded.extracted_path,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                job_id,
                source_type,
                target_type or "",
                status,
                _serialize_course(course),
                _serialize_report(report),
                extracted_path,
            ),
        )
        conn.commit()


def save_migration_job(
    job_id: str,
    source_type: str,
    target_type: str,
    course: Any,
    report: list,
    extracted_path: Optional[str] = None,
    output_path: Optional[str] = None,
) -> None:
    """Mark an existing job as migrated, preserving its report when omitted."""
    init_db()
    with _connect() as conn:
        existing = conn.execute(
            "SELECT report_json, extracted_path FROM jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()

        report_json = _serialize_report(report) if report else None
        if report_json is None and existing:
            report_json = existing["report_json"] or "[]"
        if not extracted_path and existing:
            extracted_path = existing["extracted_path"]

        conn.execute(
            """
            INSERT INTO jobs
                (job_id, source_type, target_type, status, course_json,
                 report_json, extracted_path, output_path, error, updated_at)
            VALUES (?, ?, ?, 'migrated', ?, ?, ?, ?, NULL, CURRENT_TIMESTAMP)
            ON CONFLICT(job_id) DO UPDATE SET
                source_type = excluded.source_type,
                target_type = excluded.target_type,
                status = excluded.status,
                course_json = excluded.course_json,
                report_json = excluded.report_json,
                extracted_path = excluded.extracted_path,
                output_path = excluded.output_path,
                error = NULL,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                job_id,
                source_type,
                target_type,
                _serialize_course(course),
                report_json or "[]",
                extracted_path,
                output_path,
            ),
        )
        conn.commit()


def mark_job_failed(job_id: str, error: str) -> None:
    """Record a terminal failure without discarding the stored course snapshot."""
    init_db()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE jobs
            SET status = 'failed', error = ?, updated_at = CURRENT_TIMESTAMP
            WHERE job_id = ?
            """,
            (error, job_id),
        )
        conn.commit()


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a job by ID."""
    init_db()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT job_id, source_type, target_type, status, course_json,
                   report_json, extracted_path, output_path, error,
                   created_at, updated_at
            FROM jobs WHERE job_id = ?
            """,
            (job_id,),
        ).fetchone()
    return dict(row) if row else None


def list_jobs(limit: int = 100) -> List[Dict[str, Any]]:
    """Return recent jobs without loading the potentially large course JSON."""
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT job_id, source_type, target_type, status, extracted_path,
                   output_path, error, created_at, updated_at
            FROM jobs
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (max(0, int(limit)),),
        ).fetchall()
    return [dict(row) for row in rows]


def delete_job(job_id: str) -> bool:
    """Delete a job. Returns whether a row was removed."""
    init_db()
    with _connect() as conn:
        cursor = conn.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
        conn.commit()
        return cursor.rowcount > 0
