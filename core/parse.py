from adapters.moodle import MoodleCourseParser
from adapters.openedx.course_parser import OpenEdxCourseParser
from adapters.base import SourceAdapter

class ParseService:
    def parse(self, source_path: str, source_type: str, work_dir: str) -> dict:
        """
        Dispatch to the appropriate source adapter and return its raw parsed dict.

        source_type must be one of 'openedx' or 'moodle'.
        work_dir is the scratch directory used for archive extraction.
        The returned dict is passed directly to TransformService.transform().
        """
        if source_type == "openedx":
            parser = OpenEdxCourseParser()
            return parser.parse(source_path, work_dir)
        elif source_type == "moodle":
            parser = MoodleCourseParser()
            return parser.parse(source_path, work_dir)
        else:
            raise ValueError(f"Unsupported source type: {source_type}")
