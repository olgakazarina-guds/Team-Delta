"""
Migration Service – Converts canonical Course entities to target LMS formats.

Wraps target adapters to provide a unified migration interface:
- canonical Course → Open edX (.tar.gz)
- canonical Course → Moodle (.mbz)
"""

from typing import Optional

from adapters.moodle.target_adapter import MoodleTargetAdapter
from adapters.openedx.target_adapter import OpenEdxTargetAdapter
from adapters.moodle.target_adapter import MoodleTargetAdapter
from domain.entities import Course
from persistence.repositories import save_migration_job

class MigrationService:
    """
    Service for migrating courses between LMS platforms.

    Provides a unified interface for converting canonical Course entities
    to target LMS formats (Open edX or Moodle).
    """

    def __init__(self) -> None:
        """Initialize migration service with target adapters."""
        self.openedx_target = OpenEdxTargetAdapter()
        self.moodle_target = MoodleTargetAdapter()

    def migrate_to_openedx(
        self,
        course: Course,
        output_path: str,
        source_extracted_path: Optional[str] = None,
    ) -> str:
        """
        Migrate a canonical Course to Open edX format (.tar.gz).

        Args:
            course: Canonical Course entity to convert
            output_path: Destination path for the .tar.gz file
            source_extracted_path: Optional path to extracted source assets
                (for copying asset files instead of just metadata)

        Returns:
            Absolute path to the generated Open edX package

        Example:
            >>> service = MigrationService()
            >>> output = service.migrate_to_openedx(course, "export.tar.gz")
            >>> print(output)
            "/path/to/export.tar.gz"
        """
        return self.openedx_target.generate_export(
            course, output_path, source_extracted_path
        )

    def migrate_to_moodle(
        self,
        course: Course,
        output_path: str,
        source_extracted_path: Optional[str] = None,
    ) -> str:
        """
        Migrate a canonical Course to Moodle format (.mbz).

        Args:
            course: Canonical Course entity to convert
            output_path: Destination path for the .mbz file
            source_extracted_path: Optional path to extracted source assets
                (for copying asset files instead of just metadata)

        Returns:
            Absolute path to the generated Moodle backup

        Example:
             service = MigrationService()
             output = service.migrate_to_moodle(course, "backup.mbz")
             print(output)
            "/path/to/backup.mbz"
        """
        return self.moodle_target.generate_backup(
            course, output_path, source_extracted_path
        )

    def migrate_to_openedx(self, course: Course, output_path: str, source_extracted_path: Optional[str] = None) -> str:
        result_path = self.openedx_target.generate_export(course, output_path, source_extracted_path)
        # Save job with target type 'openedx'
        save_migration_job(course.course_id, course.source_system.value, "openedx", course, [], source_extracted_path)
        return result_path
