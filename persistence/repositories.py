import json
import sqlite3
from pathlib import Path
from typing import Dict, Any, Optional

DB_PATH = Path("data/lms_converter.db")

def init_db():
    """Create tables if they don't exist."""
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

def save_job(job_id: str, source_type: str, target_type: str, course: Any, report: list, extracted_path: Optional[str] = None):
    """Save job result to database."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    course_json = course.model_dump_json() if hasattr(course, "model_dump_json") else json.dumps(course.dict())
    report_json = json.dumps([r.dict() if hasattr(r, "dict") else r for r in report])
    c.execute("""
        INSERT OR REPLACE INTO jobs (job_id, source_type, target_type, course_json, report_json, extracted_path)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (job_id, source_type, "", course_json, report_json, extracted_path))
    conn.commit()
    conn.close()

def save_migration_job(job_id: str, source_type: str, target_type: str, course: Any, report: list, extracted_path: Optional[str] = None):
    """Save migration job (with target type)."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    course_json = course.model_dump_json() if hasattr(course, "model_dump_json") else json.dumps(course.dict())
    report_json = json.dumps([r.dict() if hasattr(r, "dict") else r for r in report])
    c.execute("""
        INSERT OR REPLACE INTO jobs (job_id, source_type, target_type, course_json, report_json, extracted_path)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (job_id, source_type, target_type, course_json, report_json, extracted_path))
    conn.commit()
    conn.close()

def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve job by ID."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT job_id, source_type, target_type, course_json, report_json, extracted_path, created_at FROM jobs WHERE job_id = ?", (job_id,))
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
