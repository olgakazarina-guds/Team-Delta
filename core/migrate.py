from alembic.environment import Optional

from adapters.openedx.target_adapter import OpenEdxTargetAdapter
from adapters.moodle.target_adapter import MoodleTargetAdapter
from domain.entities import Course

class MigrationService:
    def __init__(self):
        self.target_adapter = OpenEdxTargetAdapter()
        self.target_adapter = MoodleTargetAdapter()

    def migrate_to_openedx(self, course: Course, output_path: str) -> str:
        return self.target_adapter.generate_export(course, output_path)

    def migrate_to_moodle(self, course, outputpath: str, openedx_extracted_path: Optional[str] = None) -> str:
        return self.target_adapter.generate_export(course, outputpath, openedx_extracted_path)
