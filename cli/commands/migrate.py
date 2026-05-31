from adapters.openedx.target_adapter import OpenEdxTargetAdapter
from domain.entities import Course

class MigrationService:
    def __init__(self):
        self.target_adapter = OpenEdxTargetAdapter()

    def migrate_to_openedx(self, course: Course, output_path: str) -> str:
        """
        Convert a canonical Course object into an Open edX course export (.tar.gz)
        and return the path to the generated file.
        """
        return self.target_adapter.generate_export(course, output_path)
