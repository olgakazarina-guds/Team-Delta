"""
Migration Service – Converts canonical Course entities to target LMS formats.

Wraps target adapters to provide a unified migration interface:
- canonical Course → Open edX (.tar.gz)
- canonical Course → Moodle (.mbz)
"""

from typing import Any, List, Optional

from adapters.moodle.target_adapter import MoodleTargetAdapter
from adapters.openedx.target_adapter import OpenEdxTargetAdapter
from domain.entities import Course
from persistence.repositories import mark_job_failed, save_migration_job


class MigrationService:
    """Service for migrating courses between LMS platforms."""

    def __init__(self, *, owner: str = "local") -> None:
        self.openedx_target = OpenEdxTargetAdapter()
        self.moodle_target = MoodleTargetAdapter()
        self.owner = owner

    def migrate_to_openedx(
        self,
        course: Course,
        output_path: str,
        source_extracted_path: Optional[str] = None,
        job_id: Optional[str] = None,
        report: Optional[List[Any]] = None,
    ) -> str:
        """Migrate a canonical Course to Open edX format (.tar.gz)."""
        try:
            result_path = self.openedx_target.generate_export(
                course, output_path, source_extracted_path
            )
        except Exception as exc:
            if job_id:
                mark_job_failed(
                    job_id, f"{type(exc).__name__}: {exc}", owner=self.owner
                )
            raise
        self._persist(
            course,
            "openedx",
            source_extracted_path,
            job_id,
            report,
            result_path,
        )
        return result_path

    def migrate_to_moodle(
        self,
        course: Course,
        output_path: str,
        source_extracted_path: Optional[str] = None,
        job_id: Optional[str] = None,
        report: Optional[List[Any]] = None,
    ) -> str:
        """Migrate a canonical Course to Moodle format (.mbz)."""
        try:
            result_path = self.moodle_target.generate_backup(
                course, output_path, source_extracted_path
            )
        except Exception as exc:
            if job_id:
                mark_job_failed(
                    job_id, f"{type(exc).__name__}: {exc}", owner=self.owner
                )
            raise
        self._persist(
            course,
            "moodle",
            source_extracted_path,
            job_id,
            report,
            result_path,
        )
        return result_path

    def _persist(
        self,
        course: Course,
        target: str,
        source_extracted_path: Optional[str],
        job_id: Optional[str],
        report: Optional[List[Any]],
        output_path: str,
    ) -> None:
        save_migration_job(
            job_id or course.course_id,
            course.source_system.value,
            target,
            course,
            report or [],
            source_extracted_path,
            output_path,
            owner=self.owner,
        )
