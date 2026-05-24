from adapters.openedx.course_parser import OpenEdxCourseParser
from adapters.base import SourceAdapter

class ParseService:
    def parse(self, source_path: str, source_type: str, work_dir: str) -> dict:
        if source_type == "openedx":
            parser = OpenEdxCourseParser()
            return parser.parse(source_path, work_dir)
        else:
            raise ValueError(f"Unsupported source type: {source_type}")
