"""
Parse Service – Routes source parsing to the appropriate LMS adapter.
"""

from adapters.openedx.course_parser import OpenEdxCourseParser
from adapters.moodle.course_parser import MoodleCourseParser
from core.errors import UnsupportedSourceError


class ParseService:
    """Route a source package to the appropriate LMS parser."""

    _ALIASES = {
        "openedx": "openedx",
        "open-edx": "openedx",
        "edx": "openedx",
        "moodle": "moodle",
        "mbz": "moodle",
    }

    def parse(self, source_path: str, source_type: str, work_dir: str) -> dict:
        source = self._ALIASES.get(source_type.strip().lower())
        if source == "openedx":
            return OpenEdxCourseParser().parse(source_path, work_dir)
        if source == "moodle":
            return MoodleCourseParser().parse(source_path, work_dir)
        raise UnsupportedSourceError(
            f"Unsupported source type: {source_type!r}. "
            "Supported sources: openedx, moodle"
        )
