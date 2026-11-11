"""SQLite persistence for inspection and migration jobs.

The store is deliberately small but production-oriented: WAL mode, bounded
connection timeouts, transactional writes, forward-compatible schema upgrades,
and explicit lifecycle fields so operators can distinguish inspected,
migrated, and failed jobs.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from core.config import get_settings
from core.errors import JobAccessError

DEFAULT_OWNER = "local"

_REQUIRED_COLUMNS = {
    "status": "TEXT NOT NULL DEFAULT 'inspected'",
    "output_path": "TEXT",
    "error": "TEXT",
    "updated_at": "TIMESTAMP",
    "owner": "TEXT NOT NULL DEFAULT 'local'",
}


def _database_path() -> Path:
    """Resolve the database path at call time so configuration is never stale."""
    return get_settings().db_path


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    """Open a configured connection and always close it."""
    path = _database_path()
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
            owner TEXT NOT NULL DEFAULT 'local',
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
    owner: str = DEFAULT_OWNER,
) -> None:
    """Save a newly inspected job and its canonical course snapshot."""
    init_db()
    with _connect() as conn:
        existing = conn.execute(
            "SELECT owner FROM jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        if existing and existing["owner"] != owner:
            raise JobAccessError(f"Job {job_id} belongs to another owner")
        conn.execute(
            """
            INSERT INTO jobs
                (job_id, source_type, target_type, status, owner, course_json,
                 report_json, extracted_path, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(job_id) DO UPDATE SET
                source_type = excluded.source_type,
                target_type = excluded.target_type,
                status = excluded.status,
                owner = excluded.owner,
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
                owner,
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
    *,
    owner: str = DEFAULT_OWNER,
) -> None:
    """Mark an existing job as migrated, preserving its report when omitted."""
    init_db()
    with _connect() as conn:
        existing = conn.execute(
            "SELECT report_json, extracted_path, owner FROM jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()

        if existing and existing["owner"] != owner:
            raise JobAccessError(f"Job {job_id} belongs to another owner")
        effective_owner = owner

        report_json = _serialize_report(report) if report else None
        if report_json is None and existing:
            report_json = existing["report_json"] or "[]"
        if not extracted_path and existing:
            extracted_path = existing["extracted_path"]

        conn.execute(
            """
            INSERT INTO jobs
                (job_id, source_type, target_type, status, owner, course_json,
                 report_json, extracted_path, output_path, error, updated_at)
            VALUES (?, ?, ?, 'migrated', ?, ?, ?, ?, ?, NULL, CURRENT_TIMESTAMP)
            ON CONFLICT(job_id) DO UPDATE SET
                source_type = excluded.source_type,
                target_type = excluded.target_type,
                status = excluded.status,
                owner = excluded.owner,
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
                effective_owner,
                _serialize_course(course),
                report_json or "[]",
                extracted_path,
                output_path,
            ),
        )
        conn.commit()


def mark_job_failed(
    job_id: str, error: str, *, owner: Optional[str] = None
) -> None:
    """Record a terminal failure without discarding the stored course snapshot."""
    init_db()
    with _connect() as conn:
        if owner is None:
            conn.execute(
                """
                UPDATE jobs
                SET status = 'failed', error = ?, updated_at = CURRENT_TIMESTAMP
                WHERE job_id = ?
                """,
                (error, job_id),
            )
        else:
            conn.execute(
                """
                UPDATE jobs
                SET status = 'failed', error = ?, updated_at = CURRENT_TIMESTAMP
                WHERE job_id = ? AND owner = ?
                """,
                (error, job_id, owner),
            )
        conn.commit()


def get_job(job_id: str, *, owner: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieve a job by ID, optionally constrained to its owner."""
    init_db()
    with _connect() as conn:
        if owner is None:
            row = conn.execute(
                """
                SELECT job_id, source_type, target_type, status, owner,
                       course_json, report_json, extracted_path, output_path,
                       error, created_at, updated_at
                FROM jobs WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT job_id, source_type, target_type, status, owner,
                       course_json, report_json, extracted_path, output_path,
                       error, created_at, updated_at
                FROM jobs WHERE job_id = ? AND owner = ?
                """,
                (job_id, owner),
            ).fetchone()
    return dict(row) if row else None


def list_jobs(
    limit: int = 100, *, owner: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Return recent jobs without loading the potentially large course JSON."""
    init_db()
    with _connect() as conn:
        if owner is None:
            rows = conn.execute(
                """
                SELECT job_id, source_type, target_type, status, owner,
                       extracted_path, output_path, error, created_at, updated_at
                FROM jobs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (max(0, int(limit)),),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT job_id, source_type, target_type, status, owner,
                       extracted_path, output_path, error, created_at, updated_at
                FROM jobs
                WHERE owner = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (owner, max(0, int(limit))),
            ).fetchall()
    return [dict(row) for row in rows]


def delete_job(job_id: str, *, owner: Optional[str] = None) -> bool:
    """Delete a job. Returns whether a row was removed."""
    init_db()
    with _connect() as conn:
        if owner is None:
            cursor = conn.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
        else:
            cursor = conn.execute(
                "DELETE FROM jobs WHERE job_id = ? AND owner = ?", (job_id, owner)
            )
        conn.commit()
        return cursor.rowcount > 0
