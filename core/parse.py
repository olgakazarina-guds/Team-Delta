"""
Parse Service – Routes source parsing to the appropriate LMS adapter.
"""

from adapters.openedx.course_parser import OpenEdxCourseParser
from adapters.moodle.course_parser import MoodleCourseParser

class ParseService:
    def parse(self, source_path: str, source_type: str, work_dir: str) -> dict:
        if source_type == "openedx":
            parser = OpenEdxCourseParser()
            return parser.parse(source_path, work_dir)
        elif source_type == "moodle":
            parser = MoodleCourseParser()
            return parser.parse(source_path, work_dir)
        else:
            raise ValueError(f"Unsupported source type: {source_type}")
